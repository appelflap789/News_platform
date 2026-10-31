// A small hash router: the address after # decides which page is shown.
// Patterns use :name for parameters, e.g. '/sources/:id'.

import { useEffect, useState } from 'react'

function read() {
  const raw = window.location.hash.replace(/^#/, '') || '/'
  const [path, search = ''] = raw.split('?')
  return { path: path || '/', query: Object.fromEntries(new URLSearchParams(search)) }
}

export function navigate(to, { replace = false } = {}) {
  if (replace) {
    window.location.replace(`#${to}`)
  } else {
    window.location.hash = to
  }
}

export function useLocation() {
  const [location, setLocation] = useState(read)
  useEffect(() => {
    const update = () => setLocation(read())
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return location
}

/** Parameters when `path` fits `pattern`, otherwise null. */
export function match(pattern, path) {
  const wanted = pattern.split('/').filter(Boolean)
  const given = path.split('/').filter(Boolean)
  if (wanted.length !== given.length) return null
  const params = {}
  for (let i = 0; i < wanted.length; i += 1) {
    if (wanted[i].startsWith(':')) {
      params[wanted[i].slice(1)] = decodeURIComponent(given[i])
    } else if (wanted[i] !== given[i]) {
      return null
    }
  }
  return params
}

export function Link({ to, children, ...rest }) {
  return (
    <a href={`#${to}`} {...rest}>
      {children}
    </a>
  )
}
