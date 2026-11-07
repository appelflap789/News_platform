// Single items: the pages, videos and podcast episodes you saved one at a time by their address, from anywhere,
// without following the site they come from. They belong to three sources made on first use (Saved articles,
// Saved videos, Saved podcasts); this page shows them together, with the box to save another, and the sidebar
// shows this one entry in their place.

import { useCallback, useState } from 'react'
import ArticleGrid from '../../components/ArticleGrid.jsx'
import Icon from '../../components/Icon.jsx'
import SaveLink, { hasSingleItems } from '../../components/SaveLink.jsx'
import { Chip, Empty, PageHeader } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { Link } from '../../lib/router.jsx'

// kind, chip, what to paste for it
const KINDS = [
  ['article', 'Articles', 'the address of an article, a page or a PDF'],
  ['video', 'Videos', 'the address of a YouTube video (a channel is added as a source instead)'],
  ['podcast', 'Podcasts', 'the address of an episode on Spotify'],
]

function SingleItemsPage({ query }) {
  const app = useApp()
  const [kind, setKind] = useState(KINDS.some(([value]) => value === query.kind) ? query.kind : '')
  const [refresh, setRefresh] = useState(0)
  const sourceOf = (value) => app.sources.find((source) => source.saved === value)
  const load = useCallback((page) => api.articles.list({ saved: kind || 'all', ...page }), [kind])
  const chosen = KINDS.find(([value]) => value === kind)
  const source = chosen ? sourceOf(kind) : null

  if (!hasSingleItems(app)) {
    return (
      <Empty icon="refresh" title="Restart the platform first">
        This page needs a platform started since it was built. Until then your single items are under Saved
        articles, Saved videos and Saved podcasts in the sidebar.
      </Empty>
    )
  }
  return (
    <>
      <PageHeader
        title="Single items"
        subtitle="Articles, videos and podcast episodes you saved one at a time, from any site, without following the site they come from. The last one saved first."
      />
      <SaveLink here onSaved={() => setRefresh((n) => n + 1)} />
      <div className="filters">
        <Chip active={!kind} onClick={() => setKind('')} count={app.stats.saved}>
          All
        </Chip>
        {KINDS.map(([value, label]) => (
          <Chip key={value} active={kind === value} onClick={() => setKind(value)} count={sourceOf(value)?.article_count || 0}>
            {label}
          </Chip>
        ))}
        <span className="filters__spacer" />
        {source ? (
          <Link
            to={`/sources/${source.id}`}
            className="filters__link"
            title="Whether an AI summary is written, pages behind a paywall are left out and videos are written up, for what you save next"
          >
            <Icon name="settings" size={14} /> Settings of {source.name}
          </Link>
        ) : null}
      </div>
      <ArticleGrid
        load={load}
        resetKey={kind}
        refreshKey={refresh}
        empty={
          <Empty icon="download" title={chosen ? `No saved ${chosen[1].toLowerCase()} yet` : 'Nothing saved yet'}>
            {chosen
              ? `Paste ${chosen[2]} in the box above.`
              : 'Paste the address of an article, a PDF, a YouTube video or a podcast episode on Spotify in the box above. It is stored on its own, and found by search, topics and foresight like everything else.'}
          </Empty>
        }
      />
    </>
  )
}

export default {
  id: 'single-items',
  path: '/saved',
  title: 'Single items',
  icon: 'download',
  nav: { section: 'sources', order: 0 },
  // not shown by a platform that cannot list them together yet; the three sources are shown then, as before
  navItems: (app) =>
    hasSingleItems(app)
      ? [{ key: 'single-items', to: '/saved', label: 'Single items', icon: 'download', count: app.stats.saved || undefined }]
      : [],
  component: SingleItemsPage,
}
