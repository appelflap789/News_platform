// Page registry. Every folder in src/pages with a page.jsx becomes a page of the dashboard: its route
// works and, if it asks for it, it appears in the sidebar. Nothing else has to be edited.
//
// A page.jsx default-exports:
//
//   {
//     id: 'home',                 unique name
//     path: '/',                  address after the #, with :name for parameters ('/sources/:id')
//     title: 'Home',              label in the sidebar
//     icon: 'home',               icon name from components/Icon.jsx
//     nav: { section, order },    which sidebar section it belongs to; leave out to stay off the sidebar.
//                                 `action: true` styles it as an "add" link.
//     navItems: (app) => [...]    optional: one sidebar entry per thing (per source, per topic) instead
//                                 of a single entry. Each is { key, to, label, icon | avatar, count, busy }.
//     component: HomePage,        receives { params, query }
//   }

import { match } from '../lib/router.jsx'

const modules = import.meta.glob('./*/page.jsx', { eager: true })

export const pages = Object.values(modules)
  .map((module) => module.default)
  .filter((page) => page && page.path && page.component)
  // fixed addresses first, so '/topics/new' is not read as the topic with id "new"
  .sort((a, b) => a.path.split(':').length - b.path.split(':').length)

/** Sidebar sections, top to bottom. A section without pages is not drawn. */
export const SECTIONS = [
  { id: 'main', label: '' },
  { id: 'topics', label: 'Topics' },
  { id: 'sources', label: 'Sources' },
  { id: 'platform', label: 'Platform' },
]

export function resolve(path) {
  for (const page of pages) {
    const params = match(page.path, path)
    if (params) return { page, params }
  }
  return null
}
