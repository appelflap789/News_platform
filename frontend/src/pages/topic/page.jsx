// A topic's page. It answers, in this order: what is new, how did it get here, what happened when, how much
// is there and from whom, and what to look at next. The two texts are written by Claude when you ask (or by
// themselves after a scrape, when you switch that on); everything else is counted from the library.
// The arrow keys flip to the previous and the next topic.

import { useCallback, useEffect, useRef, useState } from 'react'
import ArticleGrid from '../../components/ArticleGrid.jsx'
import Icon from '../../components/Icon.jsx'
import JobProgress, { Usage } from '../../components/JobProgress.jsx'
import Markdown from '../../components/Markdown.jsx'
import TopicEditor from '../../components/TopicEditor.jsx'
import { Avatar, Button, Chip, Empty, Notice, PageHeader, Spinner, Toggle } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { TYPE_LABELS, aboutPrice, formatDate, plural, readingTime, shortDate, timeAgo } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import { isActive, useJob } from '../../lib/useJob.js'

const TIMELINE_PAGE = 30

/** A small picture that leaves its place empty when there is none, or when it does not load. */
function Thumb({ src, className }) {
  const [broken, setBroken] = useState(false)
  return (
    <span className={className} aria-hidden="true">
      {src && !broken ? <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} /> : null}
    </span>
  )
}

/** The numbered items a text rests on: their titles, one line each (the whole title, source and date on hover). */
function Sources({ sources }) {
  const { openReader } = useApp()
  const ids = sources.map((source) => source.article_id)
  return (
    <ol className="briefing__sources">
      {sources.map((source) => (
        <li key={source.n} value={source.n}>
          <button
            type="button"
            onClick={() => openReader(source.article_id, ids)}
            title={`${source.title}\n${source.source_name} · ${source.date}`}
          >
            {source.title}
          </button>
        </li>
      ))}
    </ol>
  )
}

const citationsOf = (sources) => Object.fromEntries(sources.map((source) => [source.n, source.article_id]))
const PICTURE_LINE = /^\[\[picture (\d+)\]\]$/m

/** The picture of one of the items a text rests on, with a caption that names the item; a click opens it. */
function Figure({ source, ids, lead }) {
  const { openReader } = useApp()
  const [broken, setBroken] = useState(false)
  if (!source?.image_url || broken) return null
  return (
    <figure className={`story__figure ${lead ? 'story__figure--lead' : ''}`}>
      <button type="button" onClick={() => openReader(source.article_id, ids)} title="Open this item">
        <img src={source.image_url} alt="" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
      </button>
      <figcaption>
        <span className="story__n">{source.n}</span> {source.title} · {source.source_name}
      </figcaption>
    </figure>
  )
}

/**
 * One of the two texts as a news article: the headline, the opening line and the byline across the column,
 * then the body, which starts with the lead picture to the right of the text and has the other pictures
 * Claude placed in it; then the items it rests on. The backend cuts the text into these parts (`article`); one
 * that has not been restarted since sends the text alone, which is then the body.
 */
function Story({ text, article, sources, byline }) {
  const cut = article || { headline: '', standfirst: '', lead: null, body: text }
  const citations = citationsOf(sources)
  const ids = sources.map((source) => source.article_id)
  const byNumber = Object.fromEntries(sources.map((source) => [String(source.n), source]))
  const lead = <Figure source={byNumber[cut.lead]} ids={ids} lead />
  const words = `${cut.standfirst} ${cut.body}`.split(/\s+/).filter(Boolean).length
  // split() with a captured group gives text, number, text, number, ...: every other part is a picture
  const parts = cut.body.split(PICTURE_LINE)
  return (
    <article className="story">
      {cut.headline ? <h2 className="story__headline">{cut.headline}</h2> : null}
      {cut.standfirst ? (
        <div className="story__standfirst">
          <Markdown text={cut.standfirst} citations={citations} />
        </div>
      ) : null}
      <p className="story__byline">
        <Icon name="sparkles" size={13} /> {byline} · {readingTime(words)}
      </p>
      <div className="story__body">
        {lead}
        {parts.map((part, index) =>
          index % 2 ? (
            <Figure key={index} source={byNumber[part]} ids={ids} />
          ) : part.trim() ? (
            <Markdown key={index} text={part} citations={citations} />
          ) : null,
        )}
      </div>
      <Sources sources={sources} />
    </article>
  )
}

/** One of the two texts Claude writes: its heading, the button that (re)writes it, the job while it runs. */
function Written({ icon, title, note, button, primary, disabled, start, onWritten, kind, children }) {
  const app = useApp()
  const [jobId, setJobId] = useState(null)
  const job = useJob(jobId, (finished) => {
    if (finished.status === 'done') onWritten()
  })
  const writing = isActive(job)
  const write = async () => {
    try {
      setJobId((await start()).job_id)
    } catch (error) {
      app.fail(error)
    }
  }
  return (
    <section className={`panel briefing briefing--${kind}`}>
      <div className="panel__title">
        <h3>
          <Icon name={icon} size={17} /> {title}
        </h3>
        <span className="muted">{note}</span>
        {job && !writing ? <Usage usage={job.usage} /> : null}
        <Button variant={primary ? 'primary' : 'default'} icon="sparkles" onClick={write} busy={writing} disabled={disabled}>
          {button}
        </Button>
      </div>
      {jobId && job && (writing || job.status === 'error') ? <JobProgress job={job} compact /> : null}
      {children}
    </section>
  )
}

function WhatIsNew({ topic, reload }) {
  const app = useApp()
  const ai = app.meta.ai.available
  const { news, news_next: next, news_rewrite: again } = topic
  const price = `${aboutPrice(next.usd)} with ${next.model_label}`
  // With nothing new, the latest update can be written again from the same items: an update from before
  // headlines gets one. `news_rewrite` is missing on a platform that has not been restarted since.
  const rewrite = !next.waiting && Boolean(again)
  const setAuto = async (on) => {
    try {
      await api.topics.update(topic.id, { auto_update: on })
      reload()
    } catch (error) {
      app.fail(error)
    }
  }
  let note = 'Claude reads the items that arrived since the last update and says what changed.'
  if (news) {
    note = news.from_date === news.to_date ? formatDate(news.to_date) : `${shortDate(news.from_date)} to ${formatDate(news.to_date)}`
  }
  return (
    <Written
      kind="news"
      icon="bolt"
      title="What is new"
      note={note}
      primary={(!news && next.waiting > 0) || (rewrite && !news.article?.headline)}
      disabled={!ai || (!next.waiting && !rewrite)}
      button={
        next.waiting
          ? `${news ? 'Update' : 'Write'} · ${plural(next.waiting, 'new item')} · ${price}`
          : rewrite
            ? `Rewrite · reads ${plural(again.reading, 'item')} · ${aboutPrice(again.usd)} with ${again.model_label}`
            : 'Nothing new'
      }
      start={() => api.topics.news(topic.id, rewrite)}
      onWritten={reload}
    >
      {!ai ? (
        <p className="muted">
          This needs an Anthropic API key. <Link to="/settings">Add it in Settings.</Link>
        </p>
      ) : null}
      {news ? (
        <Story
          text={news.text}
          article={news.article}
          sources={news.sources}
          byline={`Written by Claude ${timeAgo(news.created_at)} from ${plural(news.items, 'item')}`}
        />
      ) : null}
      {topic.earlier.length ? (
        <details className="earlier">
          <summary>{plural(topic.earlier.length, 'earlier update')}</summary>
          {topic.earlier.map((note_) => (
            <div key={note_.id} className="earlier__note">
              <span className="muted">{formatDate(note_.created_at)}</span>
              {note_.article?.headline ? <strong className="earlier__headline">{note_.article.headline}</strong> : null}
              <Markdown
                text={note_.article ? [note_.article.standfirst, note_.article.body.replace(/^\[\[picture \d+\]\]$/gm, '')].filter(Boolean).join('\n\n') : note_.text}
                citations={citationsOf(note_.sources)}
              />
            </div>
          ))}
        </details>
      ) : null}
      <div className="auto-update">
        <Toggle checked={topic.auto_update} onChange={setAuto} label="Update after every scrape" disabled={!ai} />
        <span className="muted">
          <strong>Keep this up to date by itself.</strong> After a scrape, an update is written when three or more new
          items have arrived: each one {price}, counted towards what one run may spend (Settings).
        </span>
      </div>
    </Written>
  )
}

function LongRun({ topic, reload }) {
  const app = useApp()
  const ai = app.meta.ai.available
  const next = topic.long_run_next
  const note = topic.briefing ? '' : 'How the topic got here and where it stands, from its best items and the updates written so far.'
  return (
    <Written
      kind="long"
      icon="clock"
      title="The long run"
      note={note}
      primary={false}
      disabled={!ai || !next.reading}
      button={`${topic.briefing ? 'Rewrite' : 'Write'} · reads ${plural(next.reading, 'item')} · ${aboutPrice(next.usd)} with ${next.model_label}`}
      start={() => api.topics.briefing(topic.id)}
      onWritten={reload}
    >
      {topic.briefing ? (
        <Story
          text={topic.briefing}
          article={topic.briefing_article}
          sources={topic.briefing_sources}
          byline={`Written by Claude ${timeAgo(topic.briefing_at)}, citing ${plural(topic.briefing_sources.length, 'item')}`}
        />
      ) : null}
    </Written>
  )
}

function Timeline({ topic, since, version, onChanged }) {
  const app = useApp()
  const { fail, openReader } = app
  const [entries, setEntries] = useState(null)
  const [total, setTotal] = useState(0)
  const [open, setOpen] = useState({})
  const [loading, setLoading] = useState(false)

  const fetchPage = useCallback(
    async (offset) => {
      setLoading(true)
      try {
        const page = await api.topics.timeline(topic.id, { since, limit: TIMELINE_PAGE, offset })
        setEntries((current) => (offset === 0 ? page.items : [...(current || []), ...page.items]))
        setTotal(page.total)
      } catch (error) {
        fail(error)
      } finally {
        setLoading(false)
      }
    },
    [topic.id, since, fail],
  )
  const librarySeq = app.library?.seq // an item was removed from the library, or put back
  useEffect(() => {
    fetchPage(0)
  }, [fetchPage, version, librarySeq])

  const notThis = async (entry) => {
    try {
      await Promise.all(entry.ids.map((id) => api.topics.say(topic.id, id, 'out')))
      app.notify(`Removed from ${topic.name}. The topic will also collect fewer items like it.`)
      onChanged()
    } catch (error) {
      fail(error)
    }
  }

  if (!entries) return null
  const ids = entries.flatMap((entry) => entry.ids)
  let month = ''
  return (
    <section className="panel">
      <div className="panel__title">
        <h3>
          <Icon name="list" size={17} /> Timeline
        </h3>
        <span className="muted">
          {plural(total, 'entry', 'entries')}, newest first. Items that say the same thing within a few days are one entry.
        </span>
      </div>
      <ol className="timeline">
        {entries.map((entry) => {
          const label = new Date(entry.date).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
          const heading = label !== month ? label : null
          month = label
          const more = entry.more.length
          return (
            <li key={entry.id} className={entry.new ? 'timeline__entry timeline__entry--new' : 'timeline__entry'}>
              {heading ? <h4 className="timeline__month">{heading}</h4> : null}
              <div className="timeline__row">
                <time title={formatDate(entry.date)}>{shortDate(entry.date)}</time>
                <Thumb src={entry.image_url} className="timeline__thumb" />
                <div className="timeline__text">
                  <button type="button" className="timeline__title" onClick={() => openReader(entry.id, ids)}>
                    {entry.title}
                  </button>
                  {entry.summary ? <p>{entry.summary}</p> : null}
                  <div className="timeline__meta">
                    <Avatar name={entry.source_name} src={entry.source_icon} size={16} />
                    <span>{entry.source_name}</span>
                    <span>{TYPE_LABELS[entry.content_type] || entry.content_type}</span>
                    {entry.new ? <span className="timeline__flag">new</span> : null}
                    {entry.why === 'meaning' ? (
                      <span className="timeline__flag timeline__flag--meaning" title="Collected for what it is about; it does not match the topic's terms.">
                        by meaning
                      </span>
                    ) : null}
                    {entry.why === 'you' ? <span className="timeline__flag timeline__flag--meaning">added by you</span> : null}
                    {more ? (
                      <button
                        type="button"
                        className="timeline__more"
                        onClick={() => setOpen({ ...open, [entry.id]: !open[entry.id] })}
                        aria-expanded={Boolean(open[entry.id])}
                      >
                        +{more} more{entry.sources > 1 ? ` · ${entry.sources} sources` : ''}
                        <Icon name={open[entry.id] ? 'chevronDown' : 'chevronRight'} size={13} />
                      </button>
                    ) : null}
                  </div>
                  {more && open[entry.id] ? (
                    <ul className="timeline__same">
                      {entry.more.map((item) => (
                        <li key={item.id}>
                          <button type="button" onClick={() => openReader(item.id, ids)}>
                            {item.title}
                          </button>
                          <span>
                            {item.source_name} · {shortDate(item.date)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
                <button
                  type="button"
                  className="timeline__out"
                  title="Not about this topic: take it out"
                  aria-label={`Not about this topic: ${entry.title}`}
                  onClick={() => notThis(entry)}
                >
                  <Icon name="close" size={14} />
                </button>
              </div>
            </li>
          )
        })}
      </ol>
      {entries.length < total ? (
        <div className="grid__more">
          <Button onClick={() => fetchPage(entries.length)} busy={loading}>
            Show more ({(total - entries.length).toLocaleString()} left)
          </Button>
        </div>
      ) : null}
    </section>
  )
}

const TREND_WORDS = {
  spiking: ['up', 'Spiking'],
  building: ['up', 'Building'],
  steady: ['flat', 'Steady'],
  quieter: ['down', 'Quieter'],
  fading: ['down', 'Fading'],
  quiet: ['flat', 'Quiet'],
  'too little history': ['none', 'Too little history'],
}

function TrendLine({ label, value, detail }) {
  const [tone, word] = TREND_WORDS[value.label] || ['none', value.label]
  return (
    <div className="trend__line">
      <span className="trend__label">{label}</span>
      <span className={`trend__word trend__word--${tone}`}>{word}</span>
      <span className="muted">{detail}</span>
    </div>
  )
}

function Trend({ trend }) {
  const weeks = trend.weeks
  const top = Math.max(1, ...weeks.map((week) => week.count))
  const width = 100 / weeks.length
  return (
    <section className="panel trend">
      <h3>Trend</h3>
      <svg className="trend__bars" viewBox="0 0 100 34" preserveAspectRatio="none" role="img" aria-label="Items per week over the last six months">
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
        <span>{shortDate(weeks[0].start)}</span>
        <span>items per week</span>
        <span>now</span>
      </div>
      <TrendLine
        label="This week"
        value={trend.short}
        detail={`${plural(trend.short.now, 'item')}, ${trend.short.before} in the four weeks before`}
      />
      <TrendLine
        label="Three months"
        value={trend.long}
        detail={`${plural(trend.long.now, 'item')}, ${trend.long.before} in the three months before`}
      />
      <p className="trend__note">
        Compared as a share of everything the library collected in the same days, so that adding a source does
        not look like a trend. {trend.first ? `This topic's first item is from ${formatDate(trend.first)}.` : ''}
      </p>
    </section>
  )
}

function MadeOf({ topic }) {
  const most = Math.max(1, ...topic.sources.map((source) => source.matches))
  return (
    <section className="panel">
      <h3>Sources</h3>
      <ul className="made-of">
        {topic.sources.map((source) => (
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
        {topic.kinds.map((kind) => (
          <span key={kind.content_type} className={`badge badge--${kind.content_type}`}>
            {kind.n} {TYPE_LABELS[kind.content_type] || kind.content_type}
          </span>
        ))}
      </div>
      <p className="trend__note">
        {topic.by.words} by their words, {topic.by.meaning} by meaning{topic.by.you ? `, ${topic.by.you} added by you` : ''}.
        {topic.mentions ? ` ${plural(topic.mentions, 'more item')} only mention${topic.mentions === 1 ? 's' : ''} it.` : ''}
      </p>
    </section>
  )
}

function UpNext({ topic }) {
  if (!topic.up_next.length) {
    return (
      <section className="panel">
        <h3>Up next</h3>
        <p className="muted">
          Your other topics appear here, the closest one first. <Link to="/topics/new">Add a topic.</Link>
        </p>
      </section>
    )
  }
  return (
    <section className="panel">
      <h3>Up next</h3>
      <ul className="up-next">
        {topic.up_next.map((other) => (
          <li key={other.id}>
            <Link to={`/topics/${other.id}`}>
              <span className="up-next__name">{other.name}</span>
              {other.new ? <span className="nav-item__fresh">{other.new} new</span> : null}
              <span className="up-next__count">{other.matches.toLocaleString()}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function TopicPage({ params }) {
  const app = useApp()
  const { fail, refreshTopics, reader } = app
  const id = Number(params.id)
  const [topic, setTopic] = useState(null)
  const [missing, setMissing] = useState(false)
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [sort, setSort] = useState('relevance')
  const [scope, setScope] = useState('about')
  const [sourceId, setSourceId] = useState(null)
  const [version, setVersion] = useState(0)
  const [since, setSince] = useState(null) // when this page was last opened, before this visit
  const visited = useRef(null)

  const reload = useCallback(async () => {
    try {
      const loaded = await api.topics.get(id)
      setTopic(loaded)
      setMissing(false)
      if (visited.current !== id) {
        // The first load of this topic: remember what counted as new, then mark the visit.
        visited.current = id
        setSince(loaded.visited_at)
        api.topics.visit(id).then(refreshTopics).catch(() => {})
      }
    } catch (error) {
      if (error.status === 404) setMissing(true)
      else fail(error)
    }
  }, [id, fail, refreshTopics])

  useEffect(() => {
    setTopic(null)
    setDraft(null)
    setSourceId(null)
    setScope('about')
    setSince(null)
    reload()
  }, [id, reload])

  // An item was removed from the library or put back: the counts and the trend of this topic move with it.
  const librarySeq = app.library?.seq || 0
  const librarySeen = useRef(librarySeq)
  useEffect(() => {
    if (librarySeq === librarySeen.current) return
    librarySeen.current = librarySeq
    reload()
  }, [librarySeq, reload])

  // Left and right flip through the topics, as long as nothing else is using the keys.
  const previous = topic?.previous?.id
  const next = topic?.next?.id
  const busy = Boolean(reader) || Boolean(draft)
  useEffect(() => {
    if (busy) return undefined
    const onKey = (event) => {
      if (event.target.closest('input, textarea, select') || event.altKey || event.ctrlKey || event.metaKey) return
      if (event.key === 'ArrowRight' && next) navigate(`/topics/${next}`)
      if (event.key === 'ArrowLeft' && previous) navigate(`/topics/${previous}`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, previous, next])

  const load = useCallback(
    (page) => api.topics.articles(id, { sort, scope, source_id: sourceId, ...page }),
    [id, sort, scope, sourceId],
  )
  const changed = useCallback(async () => {
    await Promise.all([reload(), refreshTopics()])
    setVersion((n) => n + 1)
  }, [reload, refreshTopics])

  const save = async () => {
    setSaving(true)
    try {
      await api.topics.update(id, draft)
      setDraft(null)
      setSourceId(null)
      await changed()
    } catch (error) {
      fail(error)
    } finally {
      setSaving(false)
    }
  }
  const remove = async () => {
    if (!window.confirm(`Delete the topic "${topic.name}"? The items themselves stay in your library.`)) return
    try {
      await api.topics.remove(id)
      await refreshTopics()
      navigate('/')
    } catch (error) {
      fail(error)
    }
  }

  if (missing) {
    return (
      <Empty icon="alert" title="This topic does not exist">
        It may have been deleted.
      </Empty>
    )
  }
  if (!topic) {
    return (
      <div className="boot boot--inline">
        <Spinner size={26} />
      </div>
    )
  }

  const about = `${plural(topic.matches, 'item')} from ${plural(topic.sources.length, 'source')}`
  return (
    <div className="topic">
      {topic.previous ? (
        <nav className="flip" aria-label="Other topics">
          <Link to={`/topics/${topic.previous.id}`} title="Previous topic (left arrow key)">
            <Icon name="chevronLeft" size={15} />
            <span>{topic.previous.name}</span>
          </Link>
          <span className="flip__hint">← → to flip through your topics</span>
          <Link to={`/topics/${topic.next.id}`} title="Next topic (right arrow key)">
            <span>{topic.next.name}</span>
            <Icon name="chevronRight" size={15} />
          </Link>
        </nav>
      ) : null}

      <PageHeader title={topic.name} subtitle={`${topic.description ? `${topic.description} · ` : ''}${about}${topic.new ? ` · ${topic.new} new since your last visit` : ''}`}>
        {!draft ? (
          <>
            <Button
              icon="edit"
              onClick={() =>
                setDraft({
                  name: topic.name, description: topic.description, required_any: topic.required_any, terms: topic.terms,
                  by_meaning: topic.by_meaning, reach: topic.reach, cover_url: topic.cover_url || '',
                })
              }
            >
              Edit topic
            </Button>
            <Button variant="ghost" icon="trash" onClick={remove} aria-label="Delete topic" />
          </>
        ) : null}
      </PageHeader>

      {draft ? (
        <section className="panel">
          <TopicEditor value={draft} onChange={setDraft} pictures={topic.pictures} />
          <div className="panel__actions">
            <Button onClick={() => setDraft(null)}>Cancel</Button>
            <Button
              variant="primary"
              icon="check"
              onClick={save}
              busy={saving}
              disabled={!draft.name.trim() || (!draft.terms.length && !draft.required_any.length)}
            >
              Save topic
            </Button>
          </div>
        </section>
      ) : null}

      {topic.by_meaning && !topic.meaning.ready ? (
        <Notice kind="warn">
          This topic also collects by meaning, but that is not working yet, so it goes by its words alone.{' '}
          {topic.meaning.reason || 'No item has an embedding yet.'} <Link to="/settings">See Settings.</Link>
        </Notice>
      ) : null}

      {topic.matches === 0 && !draft ? (
        <Empty icon="search" title="Nothing in the library is about this topic yet">
          {topic.mentions
            ? `${plural(topic.mentions, 'item')} mention${topic.mentions === 1 ? 's' : ''} it without being about it; they are listed below.`
            : 'Add more sources, or widen the terms. New items are matched automatically as they are scraped.'}
        </Empty>
      ) : null}

      {topic.matches > 0 ? (
        <div className="topic__layout">
          <div className="topic__main">
            <WhatIsNew topic={topic} reload={reload} />
            <LongRun topic={topic} reload={reload} />
            <Timeline topic={topic} since={since} version={version} onChanged={changed} />
          </div>
          <aside className="topic__side">
            <Trend trend={topic.trend} />
            <MadeOf topic={topic} />
            <UpNext topic={topic} />
          </aside>
        </div>
      ) : null}

      {topic.matches + topic.mentions > 0 ? (
        <>
          <h2 className="topic__all">All items</h2>
          <div className="filters">
            <Chip active={scope === 'about'} onClick={() => setScope('about')} count={topic.matches}>
              About it
            </Chip>
            {topic.mentions ? (
              <Chip active={scope === 'mentions'} onClick={() => setScope('mentions')} count={topic.mentions}>
                Only mention it
              </Chip>
            ) : null}
            <span className="filters__label">Sources</span>
            <Chip active={!sourceId} onClick={() => setSourceId(null)}>
              All
            </Chip>
            {topic.sources.map((source) => (
              <Chip key={source.id} active={sourceId === source.id} onClick={() => setSourceId(source.id)}>
                <Avatar name={source.name} src={source.icon_url} size={18} />
                {source.name}
              </Chip>
            ))}
            <span className="filters__spacer" />
            <Chip active={sort === 'relevance'} onClick={() => setSort('relevance')}>
              Best match
            </Chip>
            <Chip active={sort === 'newest'} onClick={() => setSort('newest')}>
              Newest
            </Chip>
          </div>
          <ArticleGrid load={load} resetKey={`${id}|${sort}|${scope}|${sourceId}|${version}`} snippets />
        </>
      ) : null}
    </div>
  )
}

export default {
  id: 'topic',
  path: '/topics/:id',
  title: 'Topic',
  icon: 'topic',
  nav: { section: 'topics', order: 1 },
  navItems: (app) =>
    app.topics.map((topic) => ({
      key: `topic-${topic.id}`,
      to: `/topics/${topic.id}`,
      label: topic.name,
      icon: 'topic',
      count: topic.matches,
      fresh: topic.new,
    })),
  component: TopicPage,
}
