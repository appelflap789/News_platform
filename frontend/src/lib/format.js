// Formatting helpers shared by pages and cards.

const UNITS = [
  ['year', 31536000],
  ['month', 2592000],
  ['week', 604800],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
]

export function timeAgo(iso) {
  if (!iso) return ''
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (Number.isNaN(seconds)) return ''
  if (seconds < 60) return 'just now'
  for (const [unit, size] of UNITS) {
    const amount = Math.floor(seconds / size)
    if (amount >= 1) return `${amount} ${unit}${amount > 1 ? 's' : ''} ago`
  }
  return 'just now'
}

export function formatDate(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

/** '2026-10-09T08:00:00Z' -> '9 Oct' */
export function shortDate(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** The date to show for an article: when it was published, or else when we found it. */
export function articleDate(article) {
  return article.published_at || article.fetched_at
}

export function readingTime(words) {
  if (!words) return ''
  const minutes = Math.max(1, Math.round(words / 220))
  return minutes >= 60 ? `${Math.round(minutes / 6) / 10} h read` : `${minutes} min read`
}

export function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** The length of a video: 888 -> '14:48', 3723 -> '1:02:03' */
export function clock(seconds) {
  if (!seconds) return ''
  const pad = (number) => String(number).padStart(2, '0')
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds % 60)}` : `${minutes}:${pad(seconds % 60)}`
}

/** A large count in a few characters: 250408 -> '250K', 1234567 -> '1.2M' */
export function compact(count) {
  return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(count || 0)
}

/** A stable hue (0-359) for a name, used for avatars and placeholder thumbnails. */
export function hueOf(text) {
  let hash = 0
  for (const char of String(text || '')) hash = (hash * 31 + char.codePointAt(0)) % 360
  return hash
}

export function initials(name) {
  const words = String(name || '?').replace(/^r\//, '').split(/[\s\-_/.]+/).filter(Boolean)
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || '?').slice(0, 2)).toUpperCase()
}

export function plural(count, word, many) {
  return `${count.toLocaleString()} ${count === 1 ? word : many || `${word}s`}`
}

export function money(usd) {
  if (usd === undefined || usd === null) return ''
  return usd < 0.01 ? '< $0.01' : `$${usd.toFixed(2)}`
}

/** A price that is an estimate: 1.28 -> '$1', 25.67 -> '$26', 108 -> '$110', 0.068 -> '$0.07' */
export function roughly(usd) {
  if (usd < 0.01) return 'under $0.01'
  if (usd < 1) return `$${usd.toFixed(2)}`
  return `$${Number(usd.toPrecision(usd < 10 ? 1 : 2)).toLocaleString()}`
}

/** The same, as part of a sentence: 'about $0.08', 'under $0.01' */
export function aboutPrice(usd) {
  return usd < 0.01 ? 'under $0.01' : `about ${roughly(usd)}`
}

/** A price that is usually under a cent, said so that two of them can be told apart: 0.002 -> '0.2 cents' */
export function smallPrice(usd) {
  return usd < 0.01 ? `${(usd * 100).toFixed(1)} cents` : roughly(usd)
}

/** 'de' -> 'German' */
export function languageName(code) {
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' }).of(code) || code
  } catch {
    return code
  }
}

export const TYPE_LABELS = {
  article: 'Article',
  news: 'News',
  report: 'Report',
  paper: 'Paper',
  post: 'Post',
  document: 'Document',
  video: 'Video',
  podcast: 'Podcast',
  other: 'Other',
}

export const INTERVALS = [
  [0, 'Manual only'],
  [60, 'Every hour'],
  [360, 'Every 6 hours'],
  [720, 'Every 12 hours'],
  [1440, 'Every day'],
  [10080, 'Every week'],
]
