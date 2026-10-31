// Every call to the backend goes through here. Errors become ApiError with a message fit to show the user.

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

function describe(data, status) {
  const detail = data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
  }
  return `The request failed (${status}).`
}

async function request(method, path, body) {
  let response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('Cannot reach the platform. Is it still running?', 0)
  }
  let data = null
  try {
    data = await response.json()
  } catch {
    // no JSON body
  }
  if (!response.ok) throw new ApiError(describe(data, response.status), response.status)
  return data
}

const get = (path) => request('GET', path)
const post = (path, body = {}) => request('POST', path, body)
const patch = (path, body) => request('PATCH', path, body)
const put = (path, body) => request('PUT', path, body)
const del = (path) => request('DELETE', path)

function query(params) {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  meta: () => get('/meta'),
  stats: () => get('/stats'),
  sources: {
    list: () => get('/sources'),
    get: (id) => get(`/sources/${id}`),
    analyze: (body) => post('/sources/analyze', body),
    create: (body) => post('/sources', body),
    update: (id, body) => patch(`/sources/${id}`, body),
    remove: (id) => del(`/sources/${id}`),
    // deep = walk back through the archive; limit = stop when that many new items are stored (0 = all of it)
    scrape: (id, deep = false, limit = 0) => post(`/sources/${id}/scrape`, { deep, limit }),
    enrich: (id) => post(`/sources/${id}/enrich`),
    translate: (id) => post(`/sources/${id}/translate`),
    reanalyze: (id, body) => post(`/sources/${id}/reanalyze`, body),
    forgetLeftOut: (id) => post(`/sources/${id}/left-out/forget`),
    removePartial: (id) => post(`/sources/${id}/partial/remove`),
    // write out and write up what is waiting: as many as one run does, or with `everything` all of it
    videos: (id, retry = false, everything = false) => post(`/sources/${id}/videos`, { retry, everything }),
  },
  links: {
    // one page or one YouTube video: { job_id } to follow, or { already: true, article_id }
    save: (url) => post('/links', { url }),
  },
  scrapers: {
    list: () => get('/scrapers'),
    add: (name, options) => post(`/scrapers/${name}/add`, options),
  },
  recipes: {
    testFeed: (feed, pages = 1) => post('/recipes/test-feed', { feed, pages }),
    testArticle: (url, article) => post('/recipes/test-article', { url, article }),
  },
  articles: {
    list: (params) => get(`/articles${query(params)}`),
    get: (id) => get(`/articles/${id}`),
    remove: (id) => del(`/articles/${id}`),
    favorite: (id, on) => put(`/articles/${id}/favorite`, { on }), // star or unstar; list with { favorites: 1 }
    write: (id) => post(`/articles/${id}/write`), // one video or podcast episode: transcribe and summarise it now
    comments: (id) => post(`/articles/${id}/comments`), // an item from Reddit: read the comments and sum them up
    translate: (id) => post(`/articles/${id}/translate`), // one item that is not in English: translate it now
    similar: (id) => get(`/articles/${id}/similar`),
    topics: (id) => get(`/articles/${id}/topics`),
  },
  removed: {
    // what you took out of the library yourself: { total, items }
    list: (params) => get(`/removed${query(params)}`),
    // { restored, article_id, title }; restored is false when the item could only be let in again
    restore: (id) => post(`/removed/${id}/restore`),
  },
  topics: {
    list: () => get('/topics'),
    get: (id) => get(`/topics/${id}`),
    create: (body) => post('/topics', body),
    update: (id, body) => patch(`/topics/${id}`, body),
    remove: (id) => del(`/topics/${id}`),
    articles: (id, params) => get(`/topics/${id}/articles${query(params)}`),
    expand: (name) => post('/topics/expand', { name }),
    preview: (body) => post('/topics/preview', body),
    briefing: (id) => post(`/topics/${id}/briefing`),
    news: (id, rewrite) => post(`/topics/${id}/news${rewrite ? '?rewrite=1' : ''}`), // rewrite: the latest update again
    timeline: (id, params) => get(`/topics/${id}/timeline${query(params)}`),
    visit: (id) => post(`/topics/${id}/visit`),
    // verdict: 'in' (belongs here), 'out' (not this) or 'none' (take it back)
    say: (id, articleId, verdict) => post(`/topics/${id}/items`, { article_id: articleId, verdict }),
  },
  meaning: {
    embed: () => post('/meaning/embed'),
  },
  jobs: {
    list: () => get('/jobs'),
    get: (id) => get(`/jobs/${id}`),
    cancel: (id) => post(`/jobs/${id}/cancel`),
  },
  settings: {
    get: () => get('/settings'),
    save: (values) => put('/settings', { values }),
    saveKey: (key) => put('/settings/api-key', { key }),
    saveOtherKey: (name, key) => put(`/settings/keys/${name}`, { key }), // name: 'youtube' or 'gemini'
  },
}
