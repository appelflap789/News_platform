// Removed items: what you took out of the library yourself. No scrape stores these again. "Put back" returns
// an item as it was, with its translation, summary and transcript.

import { useCallback, useEffect, useState } from 'react'
import { Button, Empty, PageHeader, Spinner } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { TYPE_LABELS, hostOf, plural, timeAgo } from '../../lib/format.js'

const PAGE = 50

function RemovedPage() {
  const { fail, restoreRemoved, library } = useApp()
  const [items, setItems] = useState(null)
  const [total, setTotal] = useState(0)
  const [busy, setBusy] = useState(null) // the entry that is being put back
  const [loading, setLoading] = useState(false)

  const load = useCallback(
    async (offset) => {
      setLoading(true)
      try {
        const page = await api.removed.list({ limit: PAGE, offset })
        setItems((current) => (offset === 0 ? page.items : [...(current || []), ...page.items]))
        setTotal(page.total)
      } catch (error) {
        setItems((current) => current || [])
        fail(error)
      } finally {
        setLoading(false)
      }
    },
    [fail],
  )
  const librarySeq = library?.seq // something was removed or put back, here or elsewhere
  useEffect(() => {
    load(0)
  }, [load, librarySeq])

  const putBack = async (entry) => {
    setBusy(entry.id)
    await restoreRemoved(entry.id)
    setBusy(null)
  }

  return (
    <>
      <PageHeader
        title="Removed items"
        subtitle="What you took out of your library. Scrapes leave these out, also when their source still lists them."
      />
      {items === null ? (
        <div className="boot boot--inline">
          <Spinner size={26} />
        </div>
      ) : items.length === 0 ? (
        <Empty icon="trash" title="Nothing removed">
          The bin on a card, or in the reader, takes an item out of your library. It is listed here from then on,
          and you can put it back.
        </Empty>
      ) : (
        <>
          <ul className="removed">
            {items.map((entry) => (
              <li key={entry.id} className="removed__row">
                <div className="removed__text">
                  <a href={entry.url} target="_blank" rel="noreferrer" title="Open the original">
                    {entry.title || entry.url}
                  </a>
                  <small>
                    {[
                      entry.source_name,
                      TYPE_LABELS[entry.content_type] || entry.content_type,
                      hostOf(entry.url),
                      `removed ${timeAgo(entry.removed_at)}`,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </small>
                  {!entry.kept ? (
                    <small className="removed__note">
                      Its source was deleted since, so it cannot be put back as it was. Letting it in again means
                      a source that lists it collects it at its next scrape.
                    </small>
                  ) : null}
                </div>
                <Button icon={entry.kept ? 'refresh' : 'check'} busy={busy === entry.id} disabled={busy !== null} onClick={() => putBack(entry)}>
                  {entry.kept ? 'Put back' : 'Let in again'}
                </Button>
              </li>
            ))}
          </ul>
          {items.length < total ? (
            <div className="grid__more">
              <Button onClick={() => load(items.length)} busy={loading}>
                Show more ({plural(total - items.length, 'item')} left)
              </Button>
            </div>
          ) : null}
        </>
      )}
    </>
  )
}

export default {
  id: 'removed',
  path: '/removed',
  title: 'Removed items',
  icon: 'trash',
  nav: { section: 'platform', order: 3 },
  // not shown by a platform that does not remember removals yet (one not restarted since this was built)
  navItems: (app) =>
    app.canRemove
      ? [{ key: 'removed', to: '/removed', label: 'Removed items', icon: 'trash', count: app.stats.removed || undefined }]
      : [],
  component: RemovedPage,
}
