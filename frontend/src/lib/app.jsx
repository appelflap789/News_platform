// Shared state of the dashboard: what the platform can do (meta), the sources and topics shown in the
// sidebar, the article reader, toasts, and removing an item from the library. Pages read it with useApp().

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'

const AppContext = createContext(null)

/** A title as it fits in a toast. */
function shorten(title) {
  const text = String(title || 'this item')
  return `\u201c${text.length > 70 ? `${text.slice(0, 68).trimEnd()}\u2026` : text}\u201d`
}

export function AppProvider({ children }) {
  const [meta, setMeta] = useState(null)
  const [sources, setSources] = useState([])
  const [topics, setTopics] = useState([])
  const [stats, setStats] = useState(null)
  const [ready, setReady] = useState(false)
  const [failure, setFailure] = useState(null)
  const [reader, setReader] = useState(null) // { id, ids } - ids let the reader step through a list
  const [toasts, setToasts] = useState([])
  const nextToast = useRef(1)
  // What was removed from the library, put back or changed since the dashboard was opened. Every list on
  // screen watches `seq`: after 'removed' it drops the ids in `gone`, after 'restored' or 'changed' (an item
  // was transcribed and summarised from the reader) it reads itself again.
  const [library, setLibrary] = useState({ seq: 0, gone: [], last: '' })

  const refreshMeta = useCallback(async () => setMeta(await api.meta()), [])
  const refreshSources = useCallback(async () => {
    const [list, counts] = await Promise.all([api.sources.list(), api.stats()])
    setSources(list)
    setStats(counts)
    return list
  }, [])
  const refreshTopics = useCallback(async () => setTopics(await api.topics.list()), [])

  useEffect(() => {
    Promise.all([refreshMeta(), refreshSources(), refreshTopics()])
      .then(() => setReady(true))
      .catch((error) => setFailure(error))
  }, [refreshMeta, refreshSources, refreshTopics])

  // While a source is being scraped, keep the sidebar (counts, spinner) and topic counts fresh.
  const busy = sources.some((source) => source.active_job)
  useEffect(() => {
    if (!busy) return undefined
    const timer = setInterval(() => {
      refreshSources().catch(() => {})
      refreshTopics().catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [busy, refreshSources, refreshTopics])

  const dismiss = useCallback((id) => setToasts((list) => list.filter((toast) => toast.id !== id)), [])
  /** `action` is an optional { label, run, key }: a button in the toast, such as Undo. */
  const notify = useCallback(
    (message, kind = 'info', action = null) => {
      const id = nextToast.current
      nextToast.current += 1
      setToasts((list) => [...list.slice(-3), { id, message, kind, action }])
      setTimeout(() => dismiss(id), kind === 'error' || action ? 9000 : 4500)
    },
    [dismiss],
  )
  /** Show an error from a failed request. Use as `.catch(app.fail)`. */
  const fail = useCallback((error) => notify(error?.message || String(error), 'error'), [notify])

  const openReader = useCallback((id, ids = []) => setReader({ id, ids }), [])
  const closeReader = useCallback(() => setReader(null), [])

  // Only a platform that knows favorites (it counts them) gets the stars.
  const canFavorite = typeof stats?.favorites === 'number'

  /** Say that an item changed (the reader had it transcribed and summarised), so that pages read again. */
  const libraryChanged = useCallback(() => {
    setLibrary((now) => ({ ...now, seq: now.seq + 1, last: 'changed' }))
    refreshSources().catch(() => {})
  }, [refreshSources])

  /** Star an item or take its star away. Resolves to the new `favorite_at` ('' = not a favorite), or null. */
  const toggleFavorite = useCallback(
    async (article) => {
      try {
        const { favorite_at: starred } = await api.articles.favorite(article.id, !article.favorite_at)
        if (starred) notify(`Added to Favorites: ${shorten(article.title)}`)
        libraryChanged() // every list on screen shows the star, and the Favorites shelf follows
        return starred
      } catch (error) {
        fail(error)
        return null
      }
    },
    [notify, fail, libraryChanged],
  )

  // Only a platform that remembers what was removed gets the buttons: one that has not been restarted since
  // this was built would delete the item for good and collect it again at the next scrape.
  const canRemove = typeof stats?.removed === 'number'
  const recount = useCallback(() => {
    refreshSources().catch(() => {})
    refreshTopics().catch(() => {})
  }, [refreshSources, refreshTopics])

  /** Put a removed item back by its number in the list of removed items. Resolves to the answer, or null. */
  const restoreRemoved = useCallback(
    async (removedId) => {
      try {
        const back = await api.removed.restore(removedId)
        // its Undo may still be on screen (it was put back from the list instead): that offer is used up
        setToasts((list) => list.filter((toast) => toast.action?.key !== `removed-${removedId}`))
        setLibrary((now) => ({ seq: now.seq + 1, gone: now.gone.filter((id) => id !== back.article_id), last: 'restored' }))
        recount()
        notify(
          back.restored
            ? `Back in your library: ${shorten(back.title)}`
            : 'Its source no longer exists, so it could not be put back as it was. It is no longer held back: a source that lists it will collect it again.',
        )
        return back
      } catch (error) {
        fail(error)
        return null
      }
    },
    [recount, notify, fail],
  )

  /** Take an item out of the library. Scrapes leave it out from then on. Resolves to whether it worked. */
  const removeArticle = useCallback(
    async (article) => {
      try {
        const gone = await api.articles.remove(article.id)
        setLibrary((now) => ({ seq: now.seq + 1, gone: [...now.gone, article.id], last: 'removed' }))
        recount()
        notify(`Removed: ${shorten(article.title)}. Scrapes will leave it out.`, 'info', {
          label: 'Undo',
          key: `removed-${gone.removed_id}`,
          run: () => restoreRemoved(gone.removed_id),
        })
        return true
      } catch (error) {
        fail(error)
        return false
      }
    },
    [recount, notify, fail, restoreRemoved],
  )

  const value = useMemo(
    () => ({
      meta, sources, topics, stats, ready, failure, reader, toasts, library, canRemove,
      refreshMeta, refreshSources, refreshTopics, notify, fail, dismiss, openReader, closeReader,
      removeArticle, restoreRemoved, libraryChanged, canFavorite, toggleFavorite,
    }),
    [meta, sources, topics, stats, ready, failure, reader, toasts, library, canRemove, refreshMeta, refreshSources,
      refreshTopics, notify, fail, dismiss, openReader, closeReader, removeArticle, restoreRemoved, libraryChanged,
      canFavorite, toggleFavorite],
  )
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  return useContext(AppContext)
}
