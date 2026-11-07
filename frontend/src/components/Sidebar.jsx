// The left-hand navigation. It has no knowledge of individual pages: it draws whatever the page
// registry (pages/index.js) says belongs in each section.

import { useState } from 'react'
import { useApp } from '../lib/app.jsx'
import { Link } from '../lib/router.jsx'
import { SECTIONS, pages } from '../pages/index.js'
import Icon from './Icon.jsx'
import { Avatar, Spinner } from './ui.jsx'

function itemsOf(section, app) {
  return pages
    .filter((page) => page.nav?.section === section.id)
    .sort((a, b) => (a.nav.order || 0) - (b.nav.order || 0))
    .flatMap((page) =>
      page.navItems
        ? page.navItems(app)
        : [{ key: page.id, to: page.path, label: page.title, icon: page.icon, action: page.nav.action }],
    )
}

const KINDS = [
  ['all', 'All'],
  ['articles', 'Articles'],
  ['videos', 'Videos'],
  ['podcasts', 'Podcasts'],
]

/** Which kind of source the Sources list shows; the choice is remembered in this browser. */
function useSourceKind() {
  const [kind, setKind] = useState(() => {
    try {
      return window.localStorage.getItem('nsp.sources.kind') || 'all'
    } catch {
      return 'all'
    }
  })
  const choose = (value) => {
    setKind(value)
    try {
      window.localStorage.setItem('nsp.sources.kind', value)
    } catch {
      // private browsing: the choice lasts until the page is closed
    }
  }
  return [kind, choose]
}

export default function Sidebar({ current, open, onClose }) {
  const app = useApp()
  const ai = app.meta.ai.available
  const [kind, setKind] = useSourceKind()

  return (
    <>
      {open ? <div className="sidebar__scrim" onClick={onClose} /> : null}
      <nav className={`sidebar ${open ? 'sidebar--open' : ''}`} aria-label="Pages">
        <Link to="/" className="brand">
          <span className="brand__mark">
            <Icon name="list" size={18} />
          </span>
          <span>
            <strong>News Scraper</strong>
            <small>Platform</small>
          </span>
        </Link>

        <div className="sidebar__scroll">
          {SECTIONS.map((section) => {
            const all = itemsOf(section, app)
            if (!all.length) return null
            const sorted = section.id === 'sources'
            // an entry without a kind (Single items, Add source) belongs to every choice
            const items = sorted ? all.filter((item) => kind === 'all' || !item.kind || item.kind === kind) : all
            return (
              <div key={section.id} className="nav-section">
                {section.label ? (
                  <h2>
                    {section.label}
                    {sorted ? (
                      <select value={kind} onChange={(event) => setKind(event.target.value)} aria-label="Which sources to show">
                        {KINDS.map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    ) : null}
                  </h2>
                ) : null}
                {sorted && kind !== 'all' && !items.some((item) => item.kind) ? (
                  <p className="nav-section__empty">No {kind === 'videos' ? 'video' : kind === 'podcasts' ? 'podcast' : 'article'} sources yet.</p>
                ) : null}
                {items.map((item) => (
                  <Link
                    key={item.key}
                    to={item.to}
                    className={`nav-item ${current === item.to || current.startsWith(`${item.to}/`) ? 'nav-item--active' : ''} ${item.action ? 'nav-item--action' : ''}`}
                    title={item.label}
                  >
                    {item.avatar ? (
                      <Avatar name={item.avatar.name} src={item.avatar.src} size={22} />
                    ) : (
                      <Icon name={item.icon || 'file'} size={18} />
                    )}
                    <span className="nav-item__label">{item.label}</span>
                    {item.busy ? <Spinner size={13} /> : null}
                    {!item.busy && item.fresh ? (
                      <span className="nav-item__fresh" title={`${item.fresh} new since you last opened it`}>
                        {item.fresh.toLocaleString()} new
                      </span>
                    ) : null}
                    {!item.busy && item.count !== undefined ? (
                      <span className="nav-item__count">{item.count.toLocaleString()}</span>
                    ) : null}
                  </Link>
                ))}
              </div>
            )
          })}
        </div>

        <Link to="/settings" className={`ai-status ${ai ? 'ai-status--on' : ''}`}>
          <Icon name="sparkles" size={15} />
          <span>
            <strong>{ai ? 'Claude connected' : 'Claude not connected'}</strong>
            <small>{ai ? `API key ${app.meta.ai.key_hint}` : 'Add an API key in Settings'}</small>
          </span>
        </Link>
      </nav>
    </>
  )
}
