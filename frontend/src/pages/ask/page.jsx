// Ask the library: a question answered by Claude from the passages of your own items, each claim citing where it
// comes from. An add-on: everything of it in the dashboard is in this folder, and backend/addons/ask is the rest.
// It shows only when the platform says it has it (meta.addons.ask).

import { useEffect, useRef, useState } from 'react'
import JobProgress from '../../components/JobProgress.jsx'
import Markdown from '../../components/Markdown.jsx'
import { Button, Empty, Notice, PageHeader, Spinner } from '../../components/ui.jsx'
import { useApp } from '../../lib/app.jsx'
import { aboutPrice, formatDate, money, plural, timeAgo } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import { isActive, useJob } from '../../lib/useJob.js'
import { SINCE, askApi, hasAsk, scopeLabel } from './words.js'
import './ask.css'

function NotHere() {
  return (
    <Notice kind="warn">
      Ask the library is not in the platform that is running. It starts with the next deploy; reload this page then.
    </Notice>
  )
}

/** How far the library is split into passages, with the job doing it. */
function Preparing({ status, onDone }) {
  const job = useJob(status?.job_id, onDone)
  if (!status) return null
  if (status.unavailable) {
    return <Notice kind="warn">Questions need search by meaning, and it cannot run: {status.unavailable}</Notice>
  }
  if (!status.waiting) return null
  return (
    <div className="ask-preparing">
      <p className="muted">
        Preparing the library for questions: {status.done.toLocaleString()} of {plural(status.items, 'item')} split
        into passages. Free, on the server. You can ask now; the answer comes from what is ready.
      </p>
      {status.job_id ? (
        <JobProgress job={job} compact />
      ) : (
        <Button icon="refresh" onClick={() => askApi.prepare().then(onDone)}>
          Prepare the rest
        </Button>
      )}
    </div>
  )
}

/** Where a question is asked of: the whole library, one topic, one source. */
function ScopeSelect({ draft, set }) {
  const app = useApp()
  const value = draft.topic_id ? `topic:${draft.topic_id}` : draft.source_id ? `source:${draft.source_id}` : ''
  return (
    <select
      aria-label="Ask of"
      value={value}
      onChange={(event) => {
        const [kind, id] = event.target.value.split(':')
        set({ topic_id: kind === 'topic' ? Number(id) : null, source_id: kind === 'source' ? Number(id) : null })
      }}
    >
      <option value="">The whole library</option>
      {app.topics.length ? (
        <optgroup label="One topic">
          {app.topics.map((topic) => (
            <option key={topic.id} value={`topic:${topic.id}`}>
              {topic.name}
            </option>
          ))}
        </optgroup>
      ) : null}
      {app.sources.length ? (
        <optgroup label="One source">
          {app.sources.map((source) => (
            <option key={source.id} value={`source:${source.id}`}>
              {source.name}
            </option>
          ))}
        </optgroup>
      ) : null}
    </select>
  )
}

/** The box a question is typed in. While you type, it says what the question will read and what it costs. */
function Composer({ initial, status }) {
  const app = useApp()
  const [draft, setDraft] = useState({ question: '', topic_id: null, source_id: null, since: '', ...initial })
  const [plan, setPlan] = useState(null)
  const [looking, setLooking] = useState(false)
  const [asking, setAsking] = useState(false)
  const box = useRef(null)
  const set = (values) => setDraft((now) => ({ ...now, ...values }))
  const question = draft.question.trim()

  useEffect(() => {
    if (question.length < 3) {
      setPlan(null)
      return undefined
    }
    setLooking(true)
    let stale = false
    const timer = setTimeout(() => {
      askApi
        .plan({ ...draft, question })
        .then((found) => !stale && setPlan(found))
        .catch(() => !stale && setPlan(null))
        .finally(() => !stale && setLooking(false))
    }, 500)
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [question, draft.topic_id, draft.source_id, draft.since]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    box.current?.focus()
  }, [])

  const ask = async () => {
    if (question.length < 3 || asking) return
    setAsking(true)
    try {
      const made = await askApi.ask({ ...draft, question })
      navigate(`/ask/${made.id}`)
    } catch (error) {
      app.fail(error)
      setAsking(false)
    }
  }

  const nothing = plan && !plan.items
  return (
    <section className="panel ask-composer">
      <textarea
        ref={box}
        rows={3}
        value={draft.question}
        placeholder="What do you want to know? For example: What do the think tanks say about drone defence for the Baltic states?"
        onChange={(event) => set({ question: event.target.value })}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) ask()
        }}
      />
      <div className="ask-composer__row">
        <ScopeSelect draft={draft} set={set} />
        <select aria-label="From" value={draft.since} onChange={(event) => set({ since: event.target.value })}>
          {SINCE.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <span className="ask-composer__plan">
          {looking ? <Spinner size={14} /> : null}
          {plan && !looking ? (
            nothing ? (
              <span className="ask-warn">Nothing in {draft.topic_id || draft.source_id || draft.since ? 'this part of ' : ''}the library matches yet.</span>
            ) : (
              <>
                Reads {plural(plan.passages, 'passage')} from {plural(plan.items, 'item')} · {aboutPrice(plan.usd)} with{' '}
                {plan.model_label}
                {plan.weak ? <span className="ask-warn"> · The library seems to have little on this</span> : null}
              </>
            )
          ) : null}
        </span>
        <Button variant="primary" icon="sparkles" busy={asking} disabled={question.length < 3 || !status?.can_answer} onClick={ask}>
          Ask
        </Button>
      </div>
      {status && !status.can_answer ? (
        <p className="ask-warn">Asking needs an Anthropic API key: add one on the Settings page.</p>
      ) : null}
      {plan?.titles?.length && !looking ? (
        <p className="ask-composer__titles muted">
          Best matches: {plan.titles.slice(0, 4).map((title) => title.title).join(' · ')}
        </p>
      ) : null}
    </section>
  )
}

function QuestionRow({ entry }) {
  const scope = scopeLabel(entry.scope)
  return (
    <Link to={`/ask/${entry.id}`} className="ask-row">
      <span className="ask-row__question">{entry.question}</span>
      <span className="ask-row__meta">
        {scope ? <span>{scope}</span> : null}
        {entry.status === 'failed' ? <span className="ask-warn">Failed</span> : null}
        {entry.status === 'waiting' ? <span>Being answered…</span> : null}
        {entry.status === 'done' ? <span>{plural(entry.cited, 'source')}</span> : null}
        <span>{timeAgo(entry.created_at)}</span>
      </span>
    </Link>
  )
}

function useStatus() {
  const [status, setStatus] = useState(null)
  const load = () => askApi.status().then(setStatus).catch(() => setStatus(null))
  useEffect(() => {
    load()
  }, [])
  return [status, load]
}

function AskHome({ query }) {
  const app = useApp()
  const [status, reloadStatus] = useStatus()
  const [list, setList] = useState(null)
  useEffect(() => {
    if (hasAsk(app)) askApi.list().then(setList).catch(() => setList([]))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  if (!hasAsk(app)) return <NotHere />
  const initial = {
    question: query.q || '',
    topic_id: Number(query.topic) || null,
    source_id: Number(query.source) || null,
    since: query.since || '',
  }
  return (
    <div className="ask">
      <PageHeader
        title="Ask the library"
        subtitle="A question answered from your own items: the passages that match it best are read, and every claim says which item it comes from."
      />
      <Preparing status={status} onDone={reloadStatus} />
      <Composer key={JSON.stringify(initial)} initial={initial} status={status} />
      {list === null ? null : list.length ? (
        <section className="ask-history">
          <h2>Earlier questions</h2>
          {list.map((entry) => (
            <QuestionRow key={entry.id} entry={entry} />
          ))}
        </section>
      ) : (
        <p className="muted ask-hint">
          Ask the way you would ask a colleague who read everything you collected. Names, places and programmes help;
          so does keeping a question to one topic or a recent period when that is what you mean.
        </p>
      )}
    </div>
  )
}

function Quotes({ quotes }) {
  const [open, setOpen] = useState(false)
  if (!quotes?.length) return null
  const shown = open ? quotes : quotes.slice(0, 1)
  return (
    <div className="ask-quotes">
      {shown.map((quote, index) => (
        <blockquote key={index}>{quote}</blockquote>
      ))}
      {quotes.length > 1 ? (
        <button type="button" className="ask-link" onClick={() => setOpen(!open)}>
          {open ? 'Show less' : `${quotes.length - 1} more cited passage${quotes.length > 2 ? 's' : ''}`}
        </button>
      ) : null}
    </div>
  )
}

function Sources({ sources, ids }) {
  const app = useApp()
  if (!sources.length) return null
  return (
    <section className="ask-sources">
      <h2>Sources</h2>
      {sources.map((source) => (
        <div key={source.n} className={`ask-source ${source.gone ? 'is-gone' : ''}`}>
          <span className="ask-source__n">{source.n}</span>
          <div className="ask-source__body">
            {source.gone ? (
              <strong>{source.title}</strong>
            ) : (
              <button type="button" className="ask-source__title" onClick={() => app.openReader(source.article_id, ids)}>
                {source.title}
              </button>
            )}
            <span className="ask-source__meta muted">
              {source.source_name} · {formatDate(source.date)}
              {source.gone ? ' · no longer in the library' : ''}
            </span>
            <Quotes quotes={source.quotes} />
          </div>
        </div>
      ))}
    </section>
  )
}

function QuestionPage({ params }) {
  const app = useApp()
  const id = Number(params.id)
  const [found, setFound] = useState(null)
  const [missing, setMissing] = useState(false)
  const [jobId, setJobId] = useState(null)
  const load = () =>
    askApi
      .get(id)
      .then((loaded) => {
        setFound(loaded)
        if (loaded.job_id) setJobId(loaded.job_id)
      })
      .catch(() => setMissing(true))
  useEffect(() => {
    if (hasAsk(app)) load()
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  const job = useJob(jobId, () => load())

  if (!hasAsk(app)) return <NotHere />
  if (missing) {
    return (
      <Empty icon="alert" title="This question is not there" action={<Link to="/ask" className="button button--primary">Ask the library</Link>}>
        It may have been deleted.
      </Empty>
    )
  }
  if (!found) return <Spinner />

  const working = found.status === 'waiting' && (isActive(job) || (jobId && !job))
  const citations = Object.fromEntries(found.sources.map((source) => [source.n, source.article_id]))
  const ids = found.sources.filter((source) => !source.gone).map((source) => source.article_id)
  const scope = scopeLabel(found.scope)
  const again = () => {
    const params = new URLSearchParams({ q: found.question })
    if (found.scope.topic_id) params.set('topic', found.scope.topic_id)
    if (found.scope.source_id) params.set('source', found.scope.source_id)
    if (found.scope.since) params.set('since', found.scope.since)
    navigate(`/ask?${params}`)
  }
  const remove = async () => {
    try {
      await askApi.remove(id)
      navigate('/ask')
    } catch (error) {
      app.fail(error)
    }
  }

  return (
    <article className="ask ask-answer">
      <p className="ask-answer__back">
        <Link to="/ask">Ask the library</Link>
      </p>
      <h1>{found.question}</h1>
      <p className="ask-answer__byline muted">
        {scope ? `${scope} · ` : ''}
        {formatDate(found.created_at)}
      </p>
      {working || (jobId && job && isActive(job)) ? <JobProgress job={job} /> : null}
      {found.status === 'failed' ? (
        <Notice kind="warn">The question could not be answered: {found.error || 'no reason was given.'}</Notice>
      ) : null}
      {found.status === 'waiting' && !working ? (
        <Notice kind="warn">This question was not answered: the platform restarted while Claude was working on it. Ask it again.</Notice>
      ) : null}
      {found.answer ? (
        <div className="ask-answer__text">
          <Markdown text={found.answer} citations={citations} />
        </div>
      ) : null}
      <Sources sources={found.sources} ids={ids} />
      {found.read?.length ? (
        <details className="ask-read">
          <summary>Also read, not cited: {plural(found.read.length, 'item')}</summary>
          <ul>
            {found.read.map((item) => (
              <li key={item.article_id}>
                <button type="button" className="ask-link" onClick={() => app.openReader(item.article_id)}>
                  {item.title}
                </button>{' '}
                <span className="muted">
                  {item.source_name} · {formatDate(item.date)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {found.status !== 'waiting' ? (
        <footer className="ask-answer__foot">
          <span className="muted">
            {found.passages ? `${plural(found.passages, 'passage')} read · ` : ''}
            {found.model_label || ''}
            {found.cost_usd ? ` · ${money(found.cost_usd)}` : ''}
          </span>
          <Button icon="refresh" onClick={again}>
            Ask again or change it
          </Button>
          <Button icon="plus" onClick={() => navigate('/ask')}>
            New question
          </Button>
          <Button variant="ghost" icon="trash" onClick={remove}>
            Delete
          </Button>
        </footer>
      ) : null}
    </article>
  )
}

export default [
  {
    id: 'ask',
    path: '/ask',
    title: 'Ask the library',
    icon: 'ask',
    nav: { section: 'main', order: 4 },
    navItems: (app) => (hasAsk(app) ? [{ key: 'ask', to: '/ask', label: 'Ask the library', icon: 'ask' }] : []),
    component: AskHome,
  },
  { id: 'ask-question', path: '/ask/:id', title: 'Ask the library', icon: 'ask', component: QuestionPage },
]
