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
//     shelf: { order, component } optional: a shelf of its own on Home, below the topics; the component
//                                 receives { search } (what is typed in Home's search box)
//   }
//
// A page.jsx may also export a list of such pages: a part that can be taken out again (an add-on, such
// as pages/foresight) keeps all its pages in its one folder, and deleting the folder removes them.

import { match } from '../lib/router.jsx'

const modules = import.meta.glob('./*/page.jsx', { eager: true })

export const pages = Object.values(modules)
  .flatMap((module) => [].concat(module.default || []))
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

/** The shelves pages put on Home, in their order. */
export const shelves = pages
  .filter((page) => page.shelf?.component)
  .map((page) => ({ id: page.id, order: page.shelf.order || 0, component: page.shelf.component }))
  .sort((a, b) => a.order - b.order)
