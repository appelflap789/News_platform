// The scrolling wall of cards used by the home, source and topic pages. Every card has a star and a button that
// removes its item from the library; the wall follows what is starred, removed or put back anywhere in the
// dashboard. With `rows` it is a shelf instead, as on Home: that many rows of whole cards, however wide the
// screen, and a button that asks for the rest (`onShowAll`).

import { useCallback, useEffect, useRef, useState } from 'react'
import { cardFor } from '../cards/index.js'
import { useApp } from '../lib/app.jsx'
import { Button, Spinner } from './ui.jsx'

const PAGE_SIZE = 30

/** How many columns a CSS grid has right now, as the browser laid it out (also used by Home's topic shelf). */
export function useColumns(grid) {
  const [columns, setColumns] = useState(3)
  useEffect(() => {
    const element = grid.current
    if (!element || typeof ResizeObserver === 'undefined') return undefined
    const measure = () => setColumns(Math.max(1, getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  })
  return columns
}

/**
 * `load({ limit, offset })` returns { total, items }. Pass a new `resetKey` whenever the filters behind
 * `load` change, and the grid starts over. Change `refreshKey` to re-read what is on screen without
 * clearing it first (used while a scrape is adding items).
 */
export default function ArticleGrid({
  load, resetKey, refreshKey, empty, showSource = true, snippets = false, onTotal, rows = 0, onShowAll,
}) {
  const { openReader, fail, library, removeArticle, canRemove, canFavorite, toggleFavorite } = useApp()
  const grid = useRef(null)
  const columns = useColumns(grid)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const request = useRef(0)
  const loader = useRef(load)
  loader.current = load
  const report = useRef(onTotal)
  report.current = onTotal

  const fetchPage = useCallback(
    async (offset) => {
      const ticket = (request.current += 1)
      setLoading(true)
      try {
        const page = await loader.current({ limit: PAGE_SIZE, offset })
        if (ticket !== request.current) return // a newer request has replaced this one
        setItems((current) => (offset === 0 ? page.items : [...current, ...page.items]))
        setTotal(page.total)
        if (report.current) report.current(page.total)
      } catch (error) {
        if (ticket === request.current) fail(error)
      } finally {
        if (ticket === request.current) setLoading(false)
      }
    },
    [fail],
  )

  useEffect(() => {
    setItems([])
    fetchPage(0)
  }, [resetKey, fetchPage])

  const held = useRef({ items, total })
  held.current = { items, total }

  /** Read again what is on screen (and `more` items), however far it was scrolled, without clearing it first. */
  const reread = useCallback(async (more = 0) => {
    const ticket = (request.current += 1)
    const wanted = Math.max(PAGE_SIZE, held.current.items.length + more)
    let found = []
    let count = 0
    try {
      while (found.length < wanted) {
        const page = await loader.current({ limit: Math.min(100, wanted - found.length), offset: found.length })
        if (ticket !== request.current) return
        found = [...found, ...page.items]
        count = page.total
        if (!page.items.length || found.length >= count) break
      }
    } catch {
      return // what is on screen stays; the next change tries again
    }
    setItems(found)
    setTotal(count)
    setLoading(false)
    if (report.current) report.current(count)
  }, [])

  const firstRefresh = useRef(refreshKey)
  useEffect(() => {
    if (refreshKey === firstRefresh.current) return
    firstRefresh.current = refreshKey
    reread()
  }, [refreshKey, reread])

  // An item was removed from the library (here, in the reader, on another page) or put back.
  const librarySeen = useRef(library?.seq || 0)
  useEffect(() => {
    if (!library || library.seq === librarySeen.current) return
    librarySeen.current = library.seq
    if (library.last === 'restored' || library.last === 'changed') {
      reread(library.last === 'restored' ? 1 : 0) // room for the item that came back, so that nothing drops off the end
      return
    }
    const gone = new Set(library.gone)
    const kept = held.current.items.filter((item) => !gone.has(item.id))
    const dropped = held.current.items.length - kept.length
    if (!dropped) return
    const left = Math.max(0, held.current.total - dropped)
    setItems(kept)
    setTotal(left)
    if (report.current) report.current(left)
    if (!kept.length && left) fetchPage(0) // everything on screen is gone, but there is more
  }, [library, reread, fetchPage])

  // When a card goes, the next one slides under the pointer, bin and all: a double click must not take both.
  const lastRemoval = useRef(0)
  const remove = (article) => {
    if (Date.now() - lastRemoval.current < 400) return
    lastRemoval.current = Date.now()
    removeArticle(article)
  }

  if (!loading && items.length === 0) return empty || null
  const ids = items.map((item) => item.id)
  const shelf = rows > 0 ? rows * columns : 0 // the number of cards a shelf has room for
  const shown = shelf ? items.slice(0, shelf) : items

  return (
    <>
      <div className="grid" ref={grid}>
        {shown.map((article) => {
          const Card = cardFor(article.content_type)
          return (
            <Card
              key={article.id}
              article={article}
              showSource={showSource}
              snippet={snippets}
              onOpen={() => openReader(article.id, ids)}
              onRemove={canRemove ? () => remove(article) : undefined}
              onFavorite={canFavorite ? () => toggleFavorite(article) : undefined}
            />
          )
        })}
        {loading && items.length === 0
          ? Array.from({ length: shelf || 8 }, (_, index) => <div key={index} className="card card--skeleton" />)
          : null}
      </div>
      {shelf ? (
        total > shown.length && onShowAll ? (
          <div className="grid__more grid__more--shelf">
            <Button onClick={onShowAll}>Show more</Button>
          </div>
        ) : null
      ) : items.length < total ? (
        <div className="grid__more">
          <Button onClick={() => fetchPage(items.length)} busy={loading}>
            Show more ({(total - items.length).toLocaleString()} left)
          </Button>
        </div>
      ) : null}
      {loading && items.length > 0 && items.length >= total ? (
        <div className="grid__more">
          <Spinner />
        </div>
      ) : null}
    </>
  )
}
