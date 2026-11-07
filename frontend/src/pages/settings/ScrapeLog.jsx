// The scrape log: per day, every scrape and saved link, what it stored, and which source and which of its
// feeds gave an error. The backend sends the runs; they are put under the days of this browser's time zone.

import { useEffect, useMemo, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import { Chip, Empty, Notice, Spinner, Toggle } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { Link } from '../../lib/router.jsx'
import { plural } from '../../lib/format.js'

const PERIODS = [7, 14, 30]

/** 'error' when the run or one of its feeds failed, 'warn' when items were skipped, left out or partial. */
function verdict(run) {
  if (run.status === 'queued' || run.status === 'running') return 'running'
  if (run.status === 'cancelled') return 'cancelled'
  if (run.status === 'error' || run.feeds.some((feed) => feed.error)) return 'error'
  if (run.failed || run.left_out || run.partial || run.problems.length) return 'warn'
  return 'ok'
}

const ICONS = { ok: 'check', warn: 'alert', error: 'alert', cancelled: 'stop' }

function dayOf(iso) {
  const date = new Date(iso)
  const key = date.toLocaleDateString('en-CA') // YYYY-MM-DD in this browser's time zone
  const today = new Date()
  const yesterday = new Date(today.getTime() - 86400000)
  if (key === today.toLocaleDateString('en-CA')) return [key, 'Today']
  if (key === yesterday.toLocaleDateString('en-CA')) return [key, 'Yesterday']
  return [key, date.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })]
}

function counts(run) {
  const parts = [run.kind === 'save' ? (run.new ? 'saved' : 'not saved') : `${run.new.toLocaleString()} new`]
  if (run.failed) parts.push(`${run.failed} skipped`)
  if (run.left_out) parts.push(`${run.left_out} left out`)
  if (run.partial) parts.push(`${run.partial} partly read`)
  return parts.join(' · ')
}

/** The first thing that went wrong, for the closed row. */
function headline(run) {
  const feed = run.feeds.find((item) => item.error)
  if (feed) return `${feed.feed}: ${feed.error}`
  return run.error || ''
}

function Run({ run }) {
  const app = useApp()
  const [open, setOpen] = useState(false)
  const state = verdict(run)
  const problem = headline(run)
  return (
    <li className={`activity__row log__run log__run--${state}`}>
      <button type="button" className="activity__head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="activity__icon">{state === 'running' ? <Spinner size={16} /> : <Icon name={ICONS[state]} size={16} />}</span>
        <span className="activity__title">
          <strong>{run.source}</strong>
          <small>
            {run.kind === 'save' ? 'Saved link' : run.scheduled ? 'Scheduled' : 'By hand'} · {state === 'running' ? 'Running…' : counts(run)}
            {problem ? <span className="log__error"> · {problem}</span> : null}
          </small>
        </span>
        <time>{new Date(run.started_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</time>
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={16} />
      </button>
      {open ? (
        <div className="log__detail">
          {run.feeds.length ? (
            <table className="log__feeds">
              <thead>
                <tr>
                  <th>Feed</th>
                  <th>Read as</th>
                  <th>New</th>
                  <th>What went wrong</th>
                </tr>
              </thead>
              <tbody>
                {run.feeds.map((feed) => (
                  <tr key={feed.feed} className={feed.error ? 'log__feed--error' : ''}>
                    <td>{feed.feed}</td>
                    <td className="muted">{feed.scraper || '–'}</td>
                    <td>{feed.new.toLocaleString()}</td>
                    <td>
                      {feed.error ||
                        [feed.failed && `${feed.failed} skipped`, feed.left_out && `${feed.left_out} left out`, feed.partial && `${feed.partial} partly read`]
                          .filter(Boolean)
                          .join(' · ') ||
                        <span className="muted">Nothing</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {run.error && !run.feeds.some((feed) => feed.error) ? <Notice kind="warn">{run.error}</Notice> : null}
          {run.problems.length ? (
            <ul className="log__problems">
              {run.problems.map((problem, index) => (
                <li key={index} className={`log__problem--${problem.level}`}>
                  <Icon name="alert" size={13} /> {problem.msg}
                </li>
              ))}
            </ul>
          ) : null}
          {run.items.length ? (
            <ul className="log__items">
              {run.items.map((item) => (
                <li key={item.id}>
                  <button type="button" onClick={() => app.openReader(item.id, run.items.map((other) => other.id))}>
                    {item.title || 'Untitled'}
                  </button>
                </li>
              ))}
              {run.more_items ? <li className="muted">and {plural(run.more_items, 'more item')}</li> : null}
            </ul>
          ) : null}
          {run.source_id ? (
            <Link to={`/sources/${run.source_id}`} className="filters__link">
              <Icon name="external" size={14} /> Open {run.source}
            </Link>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

export default function ScrapeLog() {
  const [days, setDays] = useState(7)
  const [onlyProblems, setOnlyProblems] = useState(false)
  const [log, setLog] = useState(null)
  const [failure, setFailure] = useState('')

  useEffect(() => {
    setLog(null)
    setFailure('')
    api
      .scrapeLog(days)
      .then(setLog)
      .catch((error) => setFailure(error.status === 404 ? 'restart' : error.message))
  }, [days])

  const groups = useMemo(() => {
    const byDay = new Map()
    for (const run of log?.runs || []) {
      if (onlyProblems && !['error', 'warn'].includes(verdict(run))) continue
      const [key, label] = dayOf(run.started_at)
      if (!byDay.has(key)) byDay.set(key, { key, label, runs: [] })
      byDay.get(key).runs.push(run)
    }
    return [...byDay.values()]
  }, [log, onlyProblems])

  return (
    <section className="panel log">
      <div className="panel__title">
        <h3>
          <Icon name="activity" size={17} /> Scrape log
        </h3>
        <div className="log__controls">
          {PERIODS.map((period) => (
            <Chip key={period} active={days === period} onClick={() => setDays(period)}>
              {period} days
            </Chip>
          ))}
          <label className="log__only">
            <Toggle checked={onlyProblems} onChange={setOnlyProblems} label="Only problems" />
            Only problems
          </label>
        </div>
      </div>
      <p className="panel__lead">
        Every scrape and every saved link, by day: what came in, and which source, and which of its feeds, gave
        an error. Open a row for the items it stored and its messages. The full log of every run is on{' '}
        <Link to="/activity">Activity</Link>.
      </p>
      {failure === 'restart' ? (
        <Notice kind="warn">The scrape log needs a platform started since it was built. Restart it and come back.</Notice>
      ) : failure ? (
        <Notice kind="warn">{failure}</Notice>
      ) : log === null ? (
        <div className="boot boot--inline">
          <Spinner size={22} />
        </div>
      ) : !groups.length ? (
        <Empty icon="activity" title={onlyProblems ? 'No problems' : 'Nothing scraped'}>
          {onlyProblems ? `No scrape in the last ${days} days had an error or left anything out.` : `Nothing was scraped or saved in the last ${days} days.`}
        </Empty>
      ) : (
        groups.map((group) => {
          const added = group.runs.reduce((sum, run) => sum + run.new, 0)
          const busy = group.runs.filter((run) => verdict(run) === 'running').length
          const sources = new Set(group.runs.map((run) => run.source)).size
          const failed = group.runs.filter((run) => verdict(run) === 'error').length
          return (
            <div key={group.key} className="log__day">
              <h4>
                {group.label}
                <span className="muted">
                  {added.toLocaleString()} new from {plural(sources, 'source')}
                  {busy ? ` · ${busy} still running` : ''}
                  {failed ? <span className="log__error"> · {plural(failed, 'run')} with an error</span> : null}
                </span>
              </h4>
              <ul className="activity">
                {group.runs.map((run) => (
                  <Run key={run.id} run={run} />
                ))}
              </ul>
            </div>
          )
        })
      )}
    </section>
  )
}
