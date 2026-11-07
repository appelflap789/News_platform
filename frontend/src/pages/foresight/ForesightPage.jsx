// One foresight. Four ways to look at it: the wheel (the picture), the chains (the same, read left to right),
// the literature (how the library reacts to the signal) and the signposts (what the platform watches for).
// A consequence opens in a panel beside the wheel or the chains. Every Claude step is a button with its price.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import JobProgress from '../../components/JobProgress.jsx'
import { Button, Empty, Field, Notice, PageHeader, Spinner, Tabs } from '../../components/ui.jsx'
import { useApp } from '../../lib/app.jsx'
import { aboutPrice, formatDate, money, plural } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import { isActive, useJob } from '../../lib/useJob.js'
import Chains from './Chains.jsx'
import Literature, { Reading } from './Literature.jsx'
import NodePanel, { OwnConsequence } from './NodePanel.jsx'
import Signposts from './Signposts.jsx'
import Wheel, { WheelKey } from './Wheel.jsx'
import { HORIZONS, KINDS, STANDINGS, foresightApi, hasForesight } from './words.js'

const VIEWS = [
  ['wheel', 'Wheel'],
  ['chains', 'Chains'],
  ['literature', 'Literature'],
  ['signposts', 'Signposts'],
]

/** The view last chosen, remembered in this browser; a phone starts with the chains. */
function useView() {
  const [view, setView] = useState(() => {
    try {
      const kept = window.localStorage.getItem('nsp.foresight.view')
      if (kept && VIEWS.some(([id]) => id === kept)) return kept
    } catch {
      // private browsing: nothing is remembered
    }
    return window.matchMedia?.('(max-width: 720px)').matches ? 'chains' : 'wheel'
  })
  const choose = (value) => {
    setView(value)
    try {
      window.localStorage.setItem('nsp.foresight.view', value)
    } catch {
      // the choice lasts until the page is closed
    }
  }
  return [view, choose]
}

function Editor({ foresight, onSaved, onCancel }) {
  const app = useApp()
  const [draft, setDraft] = useState({
    name: foresight.name, statement: foresight.statement, kind: foresight.kind, horizon: foresight.horizon,
    note: foresight.note, topic_id: foresight.topic_id,
  })
  const [saving, setSaving] = useState(false)
  const set = (key, value) => setDraft((now) => ({ ...now, [key]: value }))
  const save = async () => {
    setSaving(true)
    try {
      onSaved(await foresightApi.update(foresight.id, draft))
    } catch (error) {
      app.fail(error)
    } finally {
      setSaving(false)
    }
  }
  return (
    <section className="panel">
      <div className="fs-form">
        <Field label="Name">
          <input value={draft.name} onChange={(event) => set('name', event.target.value)} maxLength={120} />
        </Field>
        <Field label="Kind">
          <select value={draft.kind} onChange={(event) => set('kind', event.target.value)}>
            {Object.entries(KINDS).map(([key, about]) => (
              <option key={key} value={key}>
                {about.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="What you expect or see" wide>
          <textarea rows={2} value={draft.statement} onChange={(event) => set('statement', event.target.value)} maxLength={600} />
        </Field>
        <Field label="How far ahead">
          <select value={draft.horizon} onChange={(event) => set('horizon', event.target.value)}>
            {Object.entries(HORIZONS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Read it against">
          <select value={draft.topic_id || ''} onChange={(event) => set('topic_id', event.target.value ? Number(event.target.value) : null)}>
            <option value="">Your whole library</option>
            {app.topics.map((topic) => (
              <option key={topic.id} value={topic.id}>
                The topic {topic.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="What you know" wide>
          <textarea rows={3} value={draft.note} onChange={(event) => set('note', event.target.value)} maxLength={4000} />
        </Field>
      </div>
      <p className="muted fs-small">What Claude read stays as it is until you read it again (Re-check, or Start over).</p>
      <div className="panel__actions">
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="primary" icon="check" onClick={save} busy={saving} disabled={!draft.name.trim()}>
          Save
        </Button>
      </div>
    </section>
  )
}

function Summary({ foresight }) {
  const standing = STANDINGS[foresight.standing]
  const counts = [
    plural(foresight.nodes.length, 'consequence'),
    foresight.signposts ? `${plural(foresight.signposts, 'signpost')}${foresight.seen ? `, ${foresight.seen} new ${foresight.seen === 1 ? 'item' : 'items'} matched` : ''}` : '',
    foresight.literature ? `${plural(foresight.literature.matches, 'item')} about it` : '',
    foresight.cost_usd ? `Claude so far: ${money(foresight.cost_usd)}` : '',
  ].filter(Boolean)
  return (
    <div className="fs-summary">
      {standing ? (
        <span className={`fs-standing fs-standing--${standing.tone}`} title={standing.help}>
          {standing.label}
        </span>
      ) : null}
      <p className="fs-summary__line" title={foresight.restated || undefined}>{foresight.restated || foresight.statement || foresight.name}</p>
      <p className="fs-summary__counts">{counts.join(' · ')}</p>
    </div>
  )
}

function ForesightPage({ params }) {
  const app = useApp()
  const { fail, notify } = app
  const id = Number(params.id)
  const [foresight, setForesight] = useState(null)
  const [missing, setMissing] = useState(false)
  const [view, setView] = useView()
  const [selected, setSelected] = useState(null)
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [jobId, setJobId] = useState(null)
  const visited = useRef(null)

  const reload = useCallback(async () => {
    try {
      const loaded = await foresightApi.get(id)
      setForesight(loaded)
      setMissing(false)
      if (loaded.job_id) setJobId((now) => now || loaded.job_id)
      if (visited.current !== id) {
        visited.current = id
        foresightApi.visit(id).catch(() => {})
      }
    } catch (error) {
      if (error.status === 404) setMissing(true)
      else fail(error)
    }
  }, [id, fail])

  useEffect(() => {
    setForesight(null)
    setSelected(null)
    reload()
  }, [id, reload])

  const job = useJob(jobId, (finished) => {
    reload()
    if (finished.status === 'done') {
      const made = finished.result?.consequences
      if (made !== undefined) notify(`${plural(made, 'consequence')} worked out.`)
    }
  })
  const working = isActive(job) || (jobId && !job)

  const start = async (call) => {
    try {
      setJobId((await call()).job_id)
    } catch (error) {
      fail(error)
    }
  }

  const byId = useMemo(() => Object.fromEntries((foresight?.nodes || []).map((node) => [node.id, node])), [foresight])
  const chosen = selected && byId[selected] ? byId[selected] : null

  if (!hasForesight(app)) {
    return (
      <Notice kind="warn">
        Foresight is not in the platform that is running. Restart it with <code>start.bat</code> and reload this page.
      </Notice>
    )
  }
  if (missing) {
    return (
      <Empty icon="foresight" title="This foresight does not exist" action={<Link to="/foresight" className="button button--primary">All foresights</Link>}>
        It may have been deleted.
      </Empty>
    )
  }
  if (!foresight) {
    return (
      <div className="boot">
        <Spinner size={24} />
      </div>
    )
  }

  const remove = async () => {
    if (!window.confirm(`Delete the foresight “${foresight.name}” and everything worked out in it?`)) return
    try {
      await foresightApi.remove(id)
      await app.refreshMeta()
      navigate('/foresight')
    } catch (error) {
      fail(error)
    }
  }
  const next = foresight.next
  const read = Boolean(foresight.read_at)
  const showsNodes = view === 'wheel' || view === 'chains'

  return (
    <div className="foresight">
      <PageHeader
        title={foresight.name}
        subtitle={[
          KINDS[foresight.kind]?.label,
          HORIZONS[foresight.horizon]?.toLowerCase(),
          foresight.topic ? `read against the topic ${foresight.topic.name}` : 'read against your whole library',
          read ? `read ${formatDate(foresight.read_at)}` : '',
        ].filter(Boolean).join(' · ')}
      >
        {read && next.recheck ? (
          <Button
            icon="refresh"
            busy={working}
            disabled={!foresight.ai || !next.recheck.waiting}
            onClick={() => start(() => foresightApi.recheck(id))}
            title={next.recheck.waiting ? 'Read what arrived since, and see what it changes' : 'Nothing new has arrived since it was last read'}
          >
            {next.recheck.waiting
              ? `Re-check · ${plural(next.recheck.waiting, 'new item')} · ${aboutPrice(next.recheck.usd)}`
              : 'Re-check · nothing new yet'}
          </Button>
        ) : null}
        {foresight.nodes.length >= 3 ? (
          <Button
            icon="link"
            busy={working}
            disabled={!foresight.ai}
            onClick={() => start(() => foresightApi.links(id))}
            title="Where consequences on different chains reinforce or dampen each other"
          >
            {`${foresight.links.length ? 'Find links again' : 'Find links'} · ${aboutPrice(next.links.usd)}`}
          </Button>
        ) : null}
        <Button icon="edit" onClick={() => setEditing(!editing)}>
          Edit
        </Button>
        <Button variant="ghost" icon="trash" onClick={remove} aria-label="Delete foresight" disabled={working} />
      </PageHeader>

      {editing ? (
        <Editor
          foresight={foresight}
          onCancel={() => setEditing(false)}
          onSaved={(saved) => {
            setForesight(saved)
            setEditing(false)
          }}
        />
      ) : null}

      {jobId && job && (working || job.status === 'error') ? <JobProgress job={job} startOpen={!read} /> : null}

      {!read && !working ? (
        <Notice kind={foresight.ai ? 'info' : 'warn'}>
          {foresight.ai ? (
            <>
              It has not been read against your library yet.{' '}
              <Button variant="primary" icon="sparkles" onClick={() => start(() => foresightApi.read(id))}>
                {`Read it · ${plural(next.reading.reading, 'item')} · ${aboutPrice(next.reading.usd)} with ${next.reading.model_label}`}
              </Button>
            </>
          ) : (
            <>
              Claude is not connected, so it cannot be read against your library. <Link to="/settings">Add an API key</Link>,
              or add consequences yourself below.
            </>
          )}
        </Notice>
      ) : null}

      <Summary foresight={foresight} />

      <Tabs tabs={VIEWS} current={view} onChange={setView} />

      {showsNodes ? (
        <div className={`fs-layout fs-layout--${view} ${chosen ? 'fs-layout--open' : ''}`}>
          <div className="fs-layout__main">
            {!foresight.nodes.length ? (
              <Empty icon="foresight" title={working ? 'Claude is reading it against your library' : 'No consequences yet'}>
                {working
                  ? 'The first ring appears here when it is done: four to six consequences, each with why it follows and what it rests on.'
                  : 'Read it against your library, or add a consequence of your own.'}
              </Empty>
            ) : view === 'wheel' ? (
              <>
                <Wheel foresight={foresight} nodes={foresight.nodes} links={foresight.links} selected={selected} onSelect={setSelected} />
                <WheelKey nodes={foresight.nodes} links={foresight.links} />
              </>
            ) : (
              <Chains nodes={foresight.nodes} selected={selected} onSelect={setSelected} />
            )}
            {!chosen ? (
              adding ? (
                <OwnConsequence
                  foresightId={id}
                  parent={null}
                  onCancel={() => setAdding(false)}
                  onAdded={(made) => {
                    setAdding(false)
                    reload().then(() => setSelected(made))
                  }}
                />
              ) : (
                <p className="fs-hint">
                  <Icon name="sparkles" size={14} /> Open a consequence to see why it follows, what it rests on and
                  its signposts, and to work out what follows from it.{' '}
                  <button type="button" className="fs-hint__add" onClick={() => setAdding(true)}>
                    Add a first-order consequence of your own
                  </button>
                </p>
              )
            ) : null}
          </div>
          {chosen ? (
            <NodePanel
              key={chosen.id}
              foresight={foresight}
              node={chosen}
              byId={byId}
              busy={working}
              onStart={start}
              onChanged={reload}
              onSelect={setSelected}
              onClose={() => setSelected(null)}
            />
          ) : null}
        </div>
      ) : null}

      {view === 'literature' ? (
        read ? (
          <Literature foresight={foresight} />
        ) : (
          <Empty icon="search" title="Not read yet">
            Once Claude has read it against your library, this shows what each item says on it, and when.
          </Empty>
        )
      ) : null}
      {view === 'signposts' ? <Signposts foresight={foresight} onSelect={(node) => { setSelected(node); setView('wheel') }} /> : null}
      {view === 'wheel' && read ? <div className="fs-under"><Reading foresight={foresight} /></div> : null}

      {read && foresight.ai ? (
        <p className="fs-footnote">
          Start over: read it again from scratch and work out a new first ring. What was worked out goes, your own
          consequences and notes with it.{' '}
          <button
            type="button"
            disabled={working}
            onClick={() => window.confirm('Start over? Every consequence goes, your own and your notes too.') && start(() => foresightApi.read(id))}
          >
            {`Start over · ${aboutPrice(next.reading.usd)}`}
          </button>
        </p>
      ) : null}
    </div>
  )
}

export default ForesightPage
