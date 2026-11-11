// Home, as shelves: the latest items first (two rows; "Show more" opens the whole feed), then your topics (two
// rows, the ones with something new first; "Show all" opens the rest), the shelves other pages bring
// (Foresight) and your favorites (two rows), all on cards of the same size.
// Searching or picking a kind of item turns the page into the results. The star on a card adds it to
// Favorites, the bin removes it from the library.

import { useCallback, useEffect, useRef, useState } from 'react'
import ArticleGrid, { useColumns } from '../../components/ArticleGrid.jsx'
import Icon from '../../components/Icon.jsx'
import TopicCard from '../../components/TopicCard.jsx'
import { Chip, Empty, PageHeader } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { TYPE_LABELS, plural } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import { shelves } from '../index.js'

function Welcome() {
  const { meta } = useApp()
  return (
    <div className="welcome">
      <span className="welcome__mark">
        <Icon name="rss" size={30} />
      </span>
      <h1>Plug in your first source</h1>
      <p>
        Paste the address of a news site, a think tank&rsquo;s publications page, an RSS feed, a subreddit or a PDF.
        The platform works out how the source is built and starts collecting.
      </p>
      <Link to="/add" className="button button--primary button--large">
        <Icon name="plus" size={18} />
        <span>Add a source</span>
      </Link>
      {!meta.ai.available ? (
        <p className="welcome__hint">
          Claude analysis needs an API key. <Link to="/settings">Add it in Settings</Link>, or start with Quick
          detect, which finds feeds without AI.
        </p>
      ) : null}
    </div>
  )
}

const SHELF_ROWS = 2 // the favorites and the latest items: two rows each, however wide the screen

/**
 * The topics, on cards the same size as the items': the ones with something new since you last opened them
 * first, then the ones that moved last. On plain Home a shelf of two rows like the others, with "Show all" for
 * the rest; while you search, every topic whose name or description has one of your words.
 */
function Topics({ topics, search }) {
  const grid = useRef(null)
  const columns = useColumns(grid)
  const [all, setAll] = useState(false)
  const words = search.toLowerCase().split(/\s+/).filter((word) => word.length > 2)
  const found = topics
    .filter((topic) => !words.length || words.some((word) => `${topic.name} ${topic.description}`.toLowerCase().includes(word)))
    .sort((a, b) => (b.new || 0) - (a.new || 0) || (b.latest || '').localeCompare(a.latest || ''))
  if (!found.length) return null
  const room = search || all ? found.length : SHELF_ROWS * columns
  const shown = found.slice(0, room)
  return (
    <section className="shelf">
      <div className="home-section">
        <h2>Topics</h2>
        {!search && found.length > SHELF_ROWS * columns ? (
          <button type="button" onClick={() => setAll(!all)}>
            {all ? 'Show fewer' : `Show all ${found.length}`}
          </button>
        ) : null}
        <Link to="/topics/new">New topic</Link>
      </div>
      <div className="grid grid--topics" ref={grid}>
        {shown.map((topic) => (
          <TopicCard key={topic.id} topic={topic} />
        ))}
      </div>
    </section>
  )
}

/** Your favorites, the last one you starred first: two rows, and the rest on the Favorites page. */
function Favorites({ count }) {
  const load = useCallback((page) => api.articles.list({ favorites: 1, ...page }), [])
  if (!count) return null
  return (
    <section className="shelf">
      <div className="home-section">
        <h2>Favorites</h2>
        <Link to="/favorites">See all {count.toLocaleString()}</Link>
      </div>
      <ArticleGrid load={load} resetKey="favorites" rows={SHELF_ROWS} onShowAll={() => navigate('/favorites')} />
    </section>
  )
}

function HomePage({ query }) {
  const { sources, stats, topics } = useApp()
  const [text, setText] = useState(query.q || '')
  const [search, setSearch] = useState(query.q || '')
  const [type, setType] = useState('')
  const [total, setTotal] = useState(null)
  const [wholeFeed, setWholeFeed] = useState(false) // the latest items as a shelf, or all of them
  const browsing = !search && !type // plain Home: shelves; otherwise the page is the results

  useEffect(() => {
    const timer = setTimeout(() => setSearch(text.trim()), 350)
    return () => clearTimeout(timer)
  }, [text])

  const load = useCallback(
    (page) => api.articles.list({ q: search, content_type: type, sort: search ? 'relevance' : 'newest', ...page }),
    [search, type],
  )

  if (sources.length === 0) return <Welcome />
  const types = stats?.content_types || []
  const latestItems = (
    <section className="shelf">
      <div className="home-section">
        <h2>{search ? 'Items' : type ? TYPE_LABELS[type] || type : 'Latest items'}</h2>
        {browsing && wholeFeed ? (
          <button type="button" onClick={() => setWholeFeed(false)}>
            Show fewer
          </button>
        ) : null}
      </div>
      <ArticleGrid
        load={load}
        resetKey={`${search}|${type}`}
        snippets={Boolean(search)}
        onTotal={setTotal}
        rows={browsing && !wholeFeed ? SHELF_ROWS : 0}
        onShowAll={() => setWholeFeed(true)}
        empty={
          search || type ? (
            <Empty icon="search" title="Nothing matches">
              Nothing in your library contains these words or is about this. Try fewer or different words.
            </Empty>
          ) : (
            <Empty icon="clock" title="Nothing collected yet">
              Your sources have not been scraped yet. Open a source and press Update.
            </Empty>
          )
        }
      />
    </section>
  )

  return (
    <>
      <PageHeader
        title="Home"
        subtitle={`${plural(stats?.articles || 0, 'item')} from ${plural(sources.length, 'source')}`}
      >
        <div className="search">
          <Icon name="search" size={17} />
          <input
            type="search"
            value={text}
            placeholder='Search by words or by meaning, e.g. "air defence" or is Russia a threat to NATO?'
            onChange={(event) => setText(event.target.value)}
            aria-label="Search"
          />
        </div>
      </PageHeader>

      <div className="filters">
        <Chip active={!type} onClick={() => setType('')}>
          All
        </Chip>
        {types.map((entry) => (
          <Chip
            key={entry.content_type}
            active={type === entry.content_type}
            count={entry.n}
            onClick={() => setType(entry.content_type)}
          >
            {TYPE_LABELS[entry.content_type] || entry.content_type}
          </Chip>
        ))}
        {search && total !== null ? <span className="filters__note">{plural(total, 'result')}, best match first</span> : null}
        {stats?.removed ? (
          <>
            <span className="filters__spacer" />
            <Link to="/removed" className="filters__removed" title="Items you removed from your library. Scrapes leave them out; you can put them back.">
              <Icon name="trash" size={14} />
              {stats.removed.toLocaleString()} removed
            </Link>
          </>
        ) : null}
      </div>

      {/* plain Home: the latest items come first; a search shows the matching topics above its results */}
      {browsing ? latestItems : null}
      {/* a filter on the kind of item is about items: the topics step aside */}
      {!type ? <Topics topics={topics} search={search} /> : null}
      {/* shelves other pages bring along, such as Foresight (pages/index.js) */}
      {!type ? shelves.map(({ id, component: Shelf }) => <Shelf key={id} search={search} />) : null}
      {browsing ? <Favorites count={stats?.favorites || 0} /> : null}
      {browsing ? null : latestItems}

    </>
  )
}

export default {
  id: 'home',
  path: '/',
  title: 'Home',
  icon: 'home',
  nav: { section: 'main', order: 1 },
  component: HomePage,
}
