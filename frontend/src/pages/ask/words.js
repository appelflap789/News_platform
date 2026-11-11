// The calls of Ask the library, and the words its pages use.

import { http } from '../../lib/api.js'

const { get, post, del } = http

export const askApi = {
  status: () => get('/ask/status'), // how far the library is split into passages
  prepare: () => post('/ask/prepare'),
  plan: (body) => post('/ask/plan', body), // free: what a question reads and costs
  ask: (body) => post('/ask', body), // { id, job_id }
  list: () => get('/ask/questions'),
  get: (id) => get(`/ask/questions/${id}`),
  remove: (id) => del(`/ask/questions/${id}`),
}

/** Shown only by a platform that has it (an add-on: it may have been taken out, or the platform may not have
 * been restarted since it was added). */
export const hasAsk = (app) => Boolean(app.meta?.addons?.ask)

export const SINCE = [
  ['', 'Any time'],
  ['month', 'The past month'],
  ['quarter', 'The past three months'],
  ['year', 'The past year'],
]

/** "Drone swarms · past month", for a question's scope; '' for the whole library at any time. */
export function scopeLabel(scope) {
  const parts = []
  if (scope?.topic_name) parts.push(`Topic: ${scope.topic_name}`)
  if (scope?.source_name) parts.push(`Source: ${scope.source_name}`)
  const since = SINCE.find(([key]) => key && key === scope?.since)
  if (since) parts.push(since[1])
  return parts.join(' · ')
}
