// The words of Foresight: kinds, standings, stances, domains, likelihoods, and what each basis means.

import { http } from '../../lib/api.js'

const { get, post, patch, del, query } = http

export const foresightApi = {
  list: () => get('/foresights'),
  get: (id) => get(`/foresights/${id}`),
  preview: (body) => post('/foresights/preview', body), // free: what the library has, and the price
  create: (body) => post('/foresights', body), // { id, job_id }: reading it starts straight away
  update: (id, body) => patch(`/foresights/${id}`, body),
  remove: (id) => del(`/foresights/${id}`),
  visit: (id) => post(`/foresights/${id}/visit`),
  read: (id) => post(`/foresights/${id}/read`), // read it (again: start over)
  recheck: (id) => post(`/foresights/${id}/recheck`),
  links: (id) => post(`/foresights/${id}/links`),
  articles: (id, params) => get(`/foresights/${id}/articles${query(params)}`),
  addNode: (id, body) => post(`/foresights/${id}/nodes`, body),
  plan: (nodeId) => get(`/foresight-nodes/${nodeId}/plan`),
  expand: (nodeId) => post(`/foresight-nodes/${nodeId}/expand`),
  updateNode: (nodeId, body) => patch(`/foresight-nodes/${nodeId}`, body),
  removeNode: (nodeId) => del(`/foresight-nodes/${nodeId}`),
}

/** Foresight is shown only by a platform that has it (an add-on: it may have been taken out, or the platform
 * may not have been restarted since it was added). */
export const hasForesight = (app) => Boolean(app.meta?.addons?.foresight)

export const KINDS = {
  trend: {
    label: 'Trend',
    help: 'A development already under way. See where it leads as it goes on.',
    example: 'Demographic ageing',
  },
  signal: {
    label: 'Weak signal',
    help: 'Something small or early that may grow into something that matters.',
    example: 'Navies buy cheap lasers against drones',
  },
  event: {
    label: 'Event',
    help: 'Something that happened, or may happen. Think through what follows from it.',
    example: 'The Strait of Hormuz stays closed through the winter',
  },
}

export const HORIZONS = { months: 'Next months', years: 'Next few years', decades: 'Next decades' }
export const HORIZON_SHORT = { months: 'months', years: 'years', decades: 'decades' }

export const STANDINGS = {
  borne_out: { label: 'Borne out', tone: 'ok', help: 'Your library bears the statement out.' },
  partly: { label: 'Partly borne out', tone: 'warn', help: 'Your library bears it out in part, or with an important nuance.' },
  contested: { label: 'Contested', tone: 'danger', help: 'Your sources disagree, or the newest contradict it.' },
  thin: { label: 'Little in your library', tone: 'muted', help: 'Your library has too little on it to tell.' },
}

export const STANCES = {
  supports: { label: 'Supports', tone: 'ok', help: 'bears the statement out' },
  nuances: { label: 'Nuances', tone: 'warn', help: 'agrees in part, or adds an important nuance' },
  contradicts: { label: 'Contradicts', tone: 'danger', help: 'says otherwise' },
  context: { label: 'Context', tone: 'muted', help: 'gives background without taking a side' },
}

export const DOMAINS = {
  energy: 'Energy',
  economy: 'Economy',
  security: 'Security',
  politics: 'Politics',
  society: 'Society',
  technology: 'Technology',
  environment: 'Environment',
}

// The UK intelligence probability yardstick (PHIA): the word, and the middle of its range
export const LIKELIHOODS = [
  ['remote', 0.03],
  ['highly unlikely', 0.15],
  ['unlikely', 0.3],
  ['realistic possibility', 0.45],
  ['likely', 0.65],
  ['highly likely', 0.85],
  ['almost certain', 0.97],
]
const CHANCE = Object.fromEntries(LIKELIHOODS)

export const chance = (word) => CHANCE[word] ?? 0.5

/** The yardstick's word for a probability. */
export function wordFor(probability) {
  return LIKELIHOODS.reduce((best, entry) =>
    Math.abs(entry[1] - probability) < Math.abs(best[1] - probability) ? entry : best,
  )[0]
}

export const BASES = {
  library: { label: 'From your library', short: 'library', help: 'Items in your library report it, or show it beginning.' },
  argued: { label: 'Argued in a source', short: 'argued', help: 'An item argues, forecasts or recommends it. It has not been seen yet.' },
  reasoning: { label: 'Reasoning', short: 'reasoning', help: 'No item supports it: it is Claude’s inference. Its signposts say what would show it.' },
  yours: { label: 'Yours', short: 'yours', help: 'You added it.' },
}

export const STATUSES = {
  strengthened: { label: 'Strengthened', tone: 'ok' },
  happening: { label: 'Happening', tone: 'ok' },
  weakened: { label: 'Weakened', tone: 'danger' },
  contradicted: { label: 'Contradicted', tone: 'danger' },
}

export const OUTCOMES = [
  ['', 'Not looked back on yet'],
  ['happened', 'It happened'],
  ['did_not', 'It did not happen'],
  ['too_early', 'Too early to say'],
]

export const RINGS = { 1: 'First order', 2: 'Second order', 3: 'Third order' }

/** The consequences from the first ring down to this one. */
export function chainOf(node, byId) {
  const chain = [node]
  while (chain[0].parent_id && byId[chain[0].parent_id]) chain.unshift(byId[chain[0].parent_id])
  return chain
}

/** How likely the whole chain is: each step's likelihood, given the one before it, multiplied. */
export function chainChance(node, byId) {
  return chainOf(node, byId).reduce((product, step) => product * chance(step.likelihood), 1)
}

export const plainText = (text) => (text || '').replace(/\s*\[\d+\](\[\d+\])*/g, '')
