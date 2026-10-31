// The frame around every page: sidebar on the left, the current page in the middle, and the article
// reader and toasts on top. Which page is shown is decided by the page registry.

import { useEffect, useState } from 'react'
import Icon from './components/Icon.jsx'
import Reader from './components/Reader.jsx'
import Sidebar from './components/Sidebar.jsx'
import { Empty, Spinner } from './components/ui.jsx'
import { AppProvider, useApp } from './lib/app.jsx'
import { Link, useLocation } from './lib/router.jsx'
import { resolve } from './pages/index.js'

function NotFound() {
  return (
    <Empty icon="alert" title="This page does not exist" action={<Link to="/" className="button button--primary">Go home</Link>}>
      The address does not match any page of the dashboard.
    </Empty>
  )
}

function Toasts() {
  const { toasts, dismiss } = useApp()
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast--${toast.kind}`}>
          <Icon name={toast.kind === 'error' ? 'alert' : 'check'} size={16} />
          <span>{toast.message}</span>
          {toast.action ? (
            <button
              type="button"
              className="toast__action"
              onClick={() => {
                dismiss(toast.id)
                toast.action.run()
              }}
            >
              {toast.action.label}
            </button>
          ) : null}
          <button type="button" onClick={() => dismiss(toast.id)} aria-label="Dismiss">
            <Icon name="close" size={14} />
          </button>
        </div>
      ))}
    </div>
  )
}

function Shell() {
  const { ready, failure, openReader } = useApp()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  // an address ending in ?article=12 opens that article, so an item can be linked to
  const linkedArticle = Number(location.query.article)
  useEffect(() => {
    if (ready && linkedArticle) openReader(linkedArticle)
  }, [ready, linkedArticle, openReader])

  useEffect(() => {
    setMenuOpen(false)
    window.scrollTo(0, 0)
  }, [location.path])

  if (failure) {
    return (
      <div className="boot">
        <Empty icon="alert" title="The platform is not answering">
          {failure.message} Start it with <code>start.bat</code> (or <code>python run.py</code>) and reload.
        </Empty>
      </div>
    )
  }
  if (!ready) {
    return (
      <div className="boot">
        <Spinner size={28} />
      </div>
    )
  }

  const found = resolve(location.path)
  const Page = found ? found.page.component : NotFound
  return (
    <div className="shell">
      <Sidebar current={location.path} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <main className="content">
        <button type="button" className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Open menu">
          <Icon name="menu" size={20} />
        </button>
        {/* the key makes a page start fresh when its address changes (e.g. from one source to another) */}
        <Page key={location.path} params={found ? found.params : {}} query={location.query} />
      </main>
      <Reader />
      <Toasts />
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  )
}
