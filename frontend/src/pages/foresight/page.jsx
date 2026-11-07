// Foresight: trends, weak signals and events, read against the library and worked out into what follows from
// them. An add-on: everything of it in the dashboard is in this folder (its pages, its Home shelf, its menu
// entry, its styles), and backend/addons/foresight is the rest. Deleting both folders removes it; nothing else
// imports them. It shows only when the platform says it has it (meta.addons.foresight), so a platform that was
// not restarted since it was added, or that no longer has it, simply goes without.

import { useEffect, useState } from 'react'
import { Button, Empty, Notice, PageHeader } from '../../components/ui.jsx'
import { useApp } from '../../lib/app.jsx'
import { plural } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import ForesightCard, { NewForesightCard } from './ForesightCard.jsx'
import ForesightPage from './ForesightPage.jsx'
import NewForesight from './NewForesight.jsx'
import { foresightApi, hasForesight } from './words.js'
import './foresight.css'

function useForesights() {
  const app = useApp()
  const [list, setList] = useState(null)
  const shown = hasForesight(app)
  useEffect(() => {
    if (!shown) return undefined
    let stale = false
    foresightApi.list().then((found) => !stale && setList(found)).catch(() => !stale && setList([]))
    return () => {
      stale = true
    }
  }, [shown, app.library?.seq])
  return shown ? list : []
}

function ForesightList() {
  const app = useApp()
  const list = useForesights()
  if (!hasForesight(app)) {
    return (
      <Notice kind="warn">
        Foresight is not in the platform that is running. Restart it with <code>start.bat</code> and reload this page.
      </Notice>
    )
  }
  return (
    <>
      <PageHeader
        title="Foresight"
        subtitle="A trend, a weak signal or an event, read against your library and worked out into what follows from it, and from that. The platform then watches for the signs."
      >
        <Button variant="primary" icon="plus" onClick={() => navigate('/foresight/new')}>
          New foresight
        </Button>
      </PageHeader>
      {list === null ? null : list.length ? (
        <div className="grid grid--topics">
          {list.map((foresight) => (
            <ForesightCard key={foresight.id} foresight={foresight} />
          ))}
        </div>
      ) : (
        <Empty icon="foresight" title="No foresights yet" action={<Link to="/foresight/new" className="button button--primary">New foresight</Link>}>
          Start with a large trend, such as demographic ageing, to see how your library reacts to it and where it leads.
          Or test something you expect, such as the Strait of Hormuz staying closed through the winter.
        </Empty>
      )}
      {app.topics.length ? (
        <section className="fs-from-topics">
          <h2>Or start from one of your topics</h2>
          <p>
            {app.topics.map((topic) => (
              <Link key={topic.id} to={`/foresight/new?topic=${topic.id}`} className="chip">
                {topic.name} <span className="chip__count">{plural(topic.matches, 'item')}</span>
              </Link>
            ))}
          </p>
        </section>
      ) : null}
    </>
  )
}

/** The Foresight shelf on Home, below the topics. While you search, only the foresights with one of your words. */
function ForesightShelf({ search }) {
  const app = useApp()
  const list = useForesights()
  if (!hasForesight(app) || list === null) return null
  const words = search.toLowerCase().split(/\s+/).filter((word) => word.length > 2)
  const found = list.filter((foresight) =>
    !words.length || words.some((word) => `${foresight.name} ${foresight.statement} ${foresight.restated}`.toLowerCase().includes(word)),
  )
  if (words.length && !found.length) return null
  return (
    <section className="shelf">
      <div className="home-section">
        <h2>Foresight</h2>
        <Link to="/foresight/new">New foresight</Link>
        {list.length ? <Link to="/foresight">See all</Link> : null}
      </div>
      <div className="grid grid--topics">
        {found.map((foresight) => (
          <ForesightCard key={foresight.id} foresight={foresight} />
        ))}
        {!list.length ? <NewForesightCard /> : null}
      </div>
    </section>
  )
}

export default [
  {
    id: 'foresight',
    path: '/foresight',
    title: 'Foresight',
    icon: 'foresight',
    nav: { section: 'main', order: 3 },
    navItems: (app) => (hasForesight(app) ? [{ key: 'foresight', to: '/foresight', label: 'Foresight', icon: 'foresight' }] : []),
    shelf: { order: 1, component: ForesightShelf },
    component: ForesightList,
  },
  { id: 'new-foresight', path: '/foresight/new', title: 'New foresight', icon: 'foresight', component: NewForesight },
  { id: 'foresight-page', path: '/foresight/:id', title: 'Foresight', icon: 'foresight', component: ForesightPage },
]
