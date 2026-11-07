// Making a foresight: what kind it is, what it says, how far ahead, what you know about it, and which part of
// the library to read it against (all of it, or one topic's items). While you type, the page says what the
// library has on it and what reading it costs; nothing is spent until you press the button.

import { useEffect, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import { Button, Field, Notice, PageHeader } from '../../components/ui.jsx'
import { useApp } from '../../lib/app.jsx'
import { aboutPrice, plural } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import { HORIZONS, KINDS, foresightApi, hasForesight } from './words.js'

export default function NewForesight({ query }) {
  const app = useApp()
  const fromTopic = app.topics.find((topic) => topic.id === Number(query.topic))
  const [draft, setDraft] = useState({
    kind: 'trend', name: fromTopic?.name || '', statement: '', horizon: 'years', note: '', topic_id: fromTopic?.id || null,
  })
  const [preview, setPreview] = useState(null)
  const [looking, setLooking] = useState(false)
  const [saving, setSaving] = useState(false)
  const set = (key, value) => setDraft((now) => ({ ...now, [key]: value }))

  const name = draft.name.trim()
  useEffect(() => {
    if (!name || !hasForesight(app)) {
      setPreview(null)
      return undefined
    }
    setLooking(true)
    let stale = false
    const timer = setTimeout(() => {
      foresightApi
        .preview({ ...draft, name })
        .then((found) => !stale && setPreview(found))
        .catch(() => !stale && setPreview(null))
        .finally(() => !stale && setLooking(false))
    }, 450)
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [name, draft.statement, draft.kind, draft.topic_id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!hasForesight(app)) {
    return (
      <Notice kind="warn">
        Foresight is not in the platform that is running. Restart it with <code>start.bat</code> and reload this page.
      </Notice>
    )
  }

  const create = async () => {
    setSaving(true)
    try {
      const made = await foresightApi.create({ ...draft, name })
      await app.refreshMeta()
      navigate(`/foresight/${made.id}`)
    } catch (error) {
      app.fail(error)
      setSaving(false)
    }
  }
  const kind = KINDS[draft.kind]

  return (
    <div className="fs-new">
      <PageHeader title="New foresight" subtitle="A trend, a weak signal or an event. Claude reads it against your library and works out what follows from it, one ring at a time." />

      <section className="panel">
        <div className="fs-kinds" role="radiogroup" aria-label="What kind of foresight">
          {Object.entries(KINDS).map(([key, about]) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={draft.kind === key}
              className={`fs-kind ${draft.kind === key ? 'is-chosen' : ''}`}
              onClick={() => set('kind', key)}
            >
              <strong>{about.label}</strong>
              <span>{about.help}</span>
              <em>e.g. {about.example}</em>
            </button>
          ))}
        </div>

        <div className="fs-form">
          <Field label="Name" help="Short, as it should stand on its card.">
            <input value={draft.name} onChange={(event) => set('name', event.target.value)} placeholder={`e.g. ${kind.example}`} maxLength={120} autoFocus />
          </Field>
          <Field
            label={draft.kind === 'trend' ? 'What exactly, if anything (optional)' : 'What you expect or see'}
            help={draft.kind === 'trend' ? 'A trend can be just its name. Say more to steer what Claude looks at.' : 'One sentence Claude can test against your library.'}
            wide
          >
            <textarea
              rows={2}
              value={draft.statement}
              onChange={(event) => set('statement', event.target.value)}
              placeholder={draft.kind === 'trend' ? 'e.g. Europe’s working-age population shrinks while defence needs grow' : 'e.g. The strait stays closed for refined products through the winter'}
              maxLength={600}
            />
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
                  The topic {topic.name} ({plural(topic.matches, 'item')})
                </option>
              ))}
            </select>
          </Field>
          <Field label="What you know (optional)" help="Your own knowledge of it. Claude builds on it, and says where your library disagrees." wide>
            <textarea rows={3} value={draft.note} onChange={(event) => set('note', event.target.value)} maxLength={4000} />
          </Field>
        </div>
      </section>

      <section className="panel fs-preview">
        {!name ? (
          <p className="muted">Give it a name to see what your library has on it.</p>
        ) : !preview ? (
          <p className="muted">{looking ? 'Looking in your library…' : 'Could not look in your library.'}</p>
        ) : (
          <>
            <p>
              <strong>{preview.matches ? plural(preview.matches, 'item') : 'Nothing'}</strong> in{' '}
              {draft.topic_id ? 'the topic' : 'your library'} {preview.matches === 1 ? 'is' : 'are'} about this
              {preview.matches > preview.reading ? `; Claude reads the ${preview.reading} that match best and the newest` : ''}.
              {looking ? <span className="muted"> Updating…</span> : null}
            </p>
            {preview.sources.length ? (
              <p className="fs-preview__sources">
                {preview.sources.map((source) => (
                  <span key={source.id}>
                    {source.name} <b>{source.matches}</b>
                  </span>
                ))}
              </p>
            ) : null}
            {preview.sample.length ? (
              <ul className="fs-preview__sample">
                {preview.sample.map((item) => (
                  <li key={item.id}>
                    {item.title} <span className="muted">· {item.source_name} · {item.date}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {!preview.matches ? (
              <Notice kind="warn">
                Your library has nothing on this yet. Claude can still work out consequences, but they will rest on
                reasoning alone; their signposts will watch for the items that would show them.
              </Notice>
            ) : null}
            {!preview.meaning ? (
              <p className="muted fs-small">Search by meaning is off, so it goes by its name alone. <Link to="/settings">Settings</Link></p>
            ) : null}
          </>
        )}
        <div className="panel__actions">
          <Button onClick={() => navigate('/foresight')}>Cancel</Button>
          <Button variant="primary" icon="sparkles" onClick={create} busy={saving} disabled={!name}>
            {preview?.ai
              ? `Create and read it · ${aboutPrice(preview.usd)} with ${preview.model_label}`
              : 'Create'}
          </Button>
          {preview && !preview.ai ? (
            <span className="muted fs-small">
              <Icon name="alert" size={13} /> Claude is not connected: you can add consequences yourself, or{' '}
              <Link to="/settings">add an API key</Link>.
            </span>
          ) : null}
        </div>
      </section>
    </div>
  )
}
