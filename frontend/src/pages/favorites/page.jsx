// Favorites: the items you starred, the last one first. Home shows the first two rows of them.

import { useCallback } from 'react'
import ArticleGrid from '../../components/ArticleGrid.jsx'
import { Empty, PageHeader } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { plural } from '../../lib/format.js'

function FavoritesPage() {
  const { stats } = useApp()
  const load = useCallback((page) => api.articles.list({ favorites: 1, ...page }), [])
  return (
    <>
      <PageHeader
        title="Favorites"
        subtitle={`${plural(stats?.favorites || 0, 'item')} you starred, the last one first. The star on a card or in the reader adds one or takes it out.`}
      />
      <ArticleGrid
        load={load}
        resetKey="favorites"
        empty={
          <Empty icon="star" title="No favorites yet">
            Point at a card and click the star, or use the star at the top of the reader. Your favorites also have a
            shelf on Home.
          </Empty>
        }
      />
    </>
  )
}

export default {
  id: 'favorites',
  path: '/favorites',
  title: 'Favorites',
  icon: 'star',
  nav: { section: 'main', order: 2 },
  // not shown by a platform that does not know favorites yet (one not restarted since they were built)
  navItems: (app) =>
    app.canFavorite
      ? [{ key: 'favorites', to: '/favorites', label: 'Favorites', icon: 'star', count: app.stats.favorites || undefined }]
      : [],
  component: FavoritesPage,
}
