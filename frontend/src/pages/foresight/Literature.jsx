// How the literature reacts: what the library says about the signal now, what each item it was read from
// says on it (supports, nuances, contradicts, or gives context) and when, how much attention it gets week by
// week and from whom, what the library does not cover, what each re-check changed, and every item about it.

import { useCallback, useMemo, useState } from 'react'
import ArticleGrid from '../../components/ArticleGrid.jsx'
import Markdown from '../../components/Markdown.jsx'
import { Avatar, Chip } from '../../components/ui.jsx'
import { Link } from '../../lib/router.jsx'
import { TYPE_LABELS, formatDate, plural, shortDate } from '../../lib/format.js'
import { ItemLink } from './NodePanel.jsx'
import { STANCES, STANDINGS, foresightApi } from './words.js'

const DAY = 86400000

/** Every item the foresight was read from, on a line of time, in the lane of the stance it takes. */
function StanceTime({ sources }) {
  const dated = sources.filter((source) => source.stance && source.date)
  if (dated.length < 2) return null
  const times = dated.map((source) => Date.parse(source.date))
  const first = Math.min(...times)
  const last = Math.max(...times, first + DAY)
  const lanes = Object.keys(STANCES)
  const ids = dated.map((source) => source.article_id)
  const x = (time) => 4 + ((time - first) / (last - first)) * 92
  return (
    <div className="stance-time">
      {lanes.map((stance) => (
        <div key={stance} className="stance-time__lane">
          <span className={`stance-time__name fs-tone--${STANCES[stance].tone}`}>{STANCES[stance].label}</span>
          <span className="stance-time__track">
            {dated
              .filter((source) => source.stance === stance)
              .map((source) => (
                <ItemLink key={source.article_id} item={source} ids={ids}>
                  <span
                    className={`stance-time__dot fs-bg--${STANCES[stance].tone}`}
                    style={{ left: `${x(Date.parse(source.date))}%` }}
                    title={`${source.title}\n${source.source_name} · ${source.date}\n${source.says}`}
                  />
                </ItemLink>
              ))}
          </span>
        </div>
      ))}
      <div className="stance-time__axis">
        <span>{shortDate(new Date(first).toISOString())}</span>
        <span>when the items appeared</span>
        <span>{shortDate(new Date(last).toISOString())}</span>
      </div>
    </div>
  )
}

function Stances({ sources }) {
  const [open, setOpen] = useState(null)
  const counted = Object.keys(STANCES).map((stance) => [stance, sources.filter((source) => source.stance === stance)])
  const total = counted.reduce((sum, [, list]) => sum + list.length, 0)
  if (!total) return null
  const ids = sources.map((source) => source.article_id)
  return (
    <section className="panel">
      <h3>How the literature reacts</h3>
      <p className="panel__lead">
        What the {plural(total, 'item')} it was read from say on it. Point at a dot to see what an item says; a click
        opens it.
      </p>
      <div className="stance-bar" role="img" aria-label="How many items take each stance">
        {counted.map(([stance, list]) =>
          list.length ? (
            <span key={stance} className={`fs-bg--${STANCES[stance].tone}`} style={{ flex: list.length }} title={`${STANCES[stance].label}: ${list.length}`} />
          ) : null,
        )}
      </div>
      <StanceTime sources={sources} />
      <div className="stance-lists">
        {counted.map(([stance, list]) =>
          list.length ? (
            <div key={stance} className="stance-list">
              <button type="button" className="stance-list__head" onClick={() => setOpen(open === stance ? null : stance)} aria-expanded={open === stance}>
                <span className={`fs-tone--${STANCES[stance].tone}`}>{STANCES[stance].label}</span>
                <span className="muted">{plural(list.length, 'item')} · {STANCES[stance].help}</span>
              </button>
              {open === stance ? (
                <ul>
                  {list.map((source) => (
                    <li key={source.article_id}>
                      <ItemLink item={source} ids={ids} />
                      <span className="muted"> {source.source_name} · {source.date}</span>
                      {source.says ? <p>{source.says}</p> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null,
        )}
      </div>
    </section>
  )
}

function Attention({ literature }) {
  const weeks = literature.trend.weeks
  const top = Math.max(1, ...weeks.map((week) => week.count))
  const width = 100 / weeks.length
  return (
    <section className="panel trend">
      <h3>Attention</h3>
      <svg className="trend__bars" viewBox="0 0 100 34" preserveAspectRatio="none" role="img" aria-label="Items about it per week over the last six months">
        {weeks.map((week, index) => {
          const height = week.count ? Math.max(1.5, (week.count / top) * 32) : 0.6
          return (
            <rect key={week.start} x={index * width + 0.4} y={34 - height} width={width - 0.8} height={height} rx="0.5">
              <title>{`Week of ${formatDate(week.start)}: ${week.count} of ${week.total} items`}</title>
            </rect>
          )
        })}
      </svg>
      <div className="trend__axis">
        <span>{weeks.length ? shortDate(weeks[0].start) : ''}</span>
        <span>items about it per week</span>
        <span>now</span>
      </div>
      <p className="trend__note">
        {plural(literature.matches, 'item')} in your library are about it
        {literature.mentions ? `, ${literature.mentions} more only mention it` : ''}.
      </p>
    </section>
  )
}

function Who({ literature }) {
  if (!literature.sources.length) return null
  const most = Math.max(1, ...literature.sources.map((source) => source.matches))
  return (
    <section className="panel">
      <h3>Who writes about it</h3>
      <ul className="made-of">
        {literature.sources.map((source) => (
          <li key={source.id}>
            <Avatar name={source.name} src={source.icon_url} size={20} />
            <Link to={`/sources/${source.id}`}>{source.name}</Link>
            <span className="made-of__bar">
              <span style={{ width: `${(source.matches / most) * 100}%` }} />
            </span>
            <span className="made-of__count">{source.matches}</span>
          </li>
        ))}
      </ul>
      <div className="made-of__kinds">
        {literature.kinds.map((kind) => (
          <span key={kind.content_type} className={`badge badge--${kind.content_type}`}>
            {kind.n} {TYPE_LABELS[kind.content_type] || kind.content_type}
          </span>
        ))}
      </div>
    </section>
  )
}

function Checks({ foresight }) {
  if (!foresight.checks.length) return null
  const byId = Object.fromEntries(foresight.nodes.map((node) => [node.id, node]))
  return (
    <section className="panel">
      <h3>Re-checks</h3>
      {foresight.checks.map((check) => {
        const citations = Object.fromEntries(check.sources.map((source) => [source.n, source.article_id]))
        return (
          <div key={check.id} className="fs-check">
            <p className="fs-check__head">
              <strong>{formatDate(check.created_at)}</strong>
              <span className="muted"> · read {plural(check.items, 'new item')}</span>
              {check.previous && check.previous !== check.standing ? (
                <span className="muted">
                  {' '}· {STANDINGS[check.previous]?.label} → <strong>{STANDINGS[check.standing]?.label}</strong>
                </span>
              ) : null}
            </p>
            <Markdown text={check.text} citations={citations} />
            {check.changes.length ? (
              <ul className="fs-check__changes">
                {check.changes.map((change) => (
                  <li key={change.node_id}>
                    <span className={`fs-tag fs-tag--${['strengthened', 'happening'].includes(change.status) ? 'ok' : 'danger'}`}>{change.status}</span>{' '}
                    {byId[change.node_id]?.text || 'A consequence that was removed since'}: <span className="muted">{change.why}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )
      })}
    </section>
  )
}

export function Reading({ foresight }) {
  const standing = STANDINGS[foresight.standing]
  const citations = useMemo(
    () => Object.fromEntries(foresight.reading_sources.map((source) => [source.n, source.article_id])),
    [foresight.reading_sources],
  )
  if (!foresight.read_at) return null
  return (
    <section className="panel fs-reading">
      <h3>What your library says</h3>
      {standing ? <span className={`fs-standing fs-standing--${standing.tone}`} title={standing.help}>{standing.label}</span> : null}
      {foresight.restated ? <p className="fs-reading__restated">{foresight.restated}</p> : null}
      <Markdown text={foresight.reading} citations={citations} />
      <p className="muted fs-small">
        Read on {formatDate(foresight.read_at)} from {plural(foresight.reading_sources.length, 'item')}.
      </p>
      {foresight.gaps.length ? (
        <div className="fs-gaps">
          <h4>What your library does not cover</h4>
          <ul>
            {foresight.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}

export default function Literature({ foresight }) {
  const [stance, setStance] = useState('')
  const [sort, setSort] = useState('relevance')
  const load = useCallback((page) => foresightApi.articles(foresight.id, { stance, sort, ...page }), [foresight.id, stance, sort])
  const sources = foresight.reading_sources
  return (
    <>
      <div className="topic__layout">
        <div className="topic__main">
          <Reading foresight={foresight} />
          <Stances sources={sources} />
          <Checks foresight={foresight} />
        </div>
        <aside className="topic__side">
          <Attention literature={foresight.literature} />
          <Who literature={foresight.literature} />
        </aside>
      </div>
      <h2 className="topic__all">The items</h2>
      <div className="filters">
        <Chip active={!stance} onClick={() => setStance('')} count={foresight.literature.matches}>
          All about it
        </Chip>
        {Object.entries(STANCES).map(([key, about]) => {
          const count = sources.filter((source) => source.stance === key).length
          return count ? (
            <Chip key={key} active={stance === key} onClick={() => setStance(key)} count={count}>
              {about.label}
            </Chip>
          ) : null
        })}
        <span className="filters__spacer" />
        <Chip active={sort === 'relevance'} onClick={() => setSort('relevance')}>
          Best match
        </Chip>
        <Chip active={sort === 'newest'} onClick={() => setSort('newest')}>
          Newest
        </Chip>
      </div>
      <ArticleGrid load={load} resetKey={`${foresight.id}|${stance}|${sort}`} />
    </>
  )
}
