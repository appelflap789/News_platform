// One consequence, opened: the chain it is part of, why it follows, what it rests on, its signposts and
// what was seen of them, your note and your look back, and the buttons to work out what follows from it, add a
// consequence of your own, or remove it.

import { useEffect, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import { Button } from '../../components/ui.jsx'
import { useApp } from '../../lib/app.jsx'
import { aboutPrice, formatDate, plural } from '../../lib/format.js'
import {
  BASES, DOMAINS, HORIZONS, LIKELIHOODS, OUTCOMES, RINGS, STATUSES, chainChance, chainOf, foresightApi, wordFor,
} from './words.js'

export function ItemLink({ item, ids, children }) {
  const { openReader } = useApp()
  if (item.gone) return <span className="fs-item fs-item--gone" title="No longer in your library">{item.title}</span>
  return (
    <button type="button" className="fs-item" onClick={() => openReader(item.article_id, ids)} title={`${item.title}\n${item.source_name} · ${item.date}`}>
      {children || item.title}
    </button>
  )
}

function Signposts({ node }) {
  if (!node.signposts?.length) return null
  return (
    <div className="fs-panel__block">
      <h4>Signposts, watched after every scrape</h4>
      <p className="muted fs-small">A match is a new item that may bear on it. Re-check reads the matches and says which way they point.</p>
      {node.signposts.map((signpost) => {
        const ids = signpost.seen.map((hit) => hit.article_id)
        const fresh = signpost.seen.filter((hit) => !hit.earlier)
        return (
          <div key={signpost.id} className={`fs-signpost fs-signpost--${signpost.direction}`}>
            <p>
              <span className={`fs-tag fs-tag--${signpost.direction === 'for' ? 'ok' : 'danger'}`}>
                {signpost.direction === 'for' ? 'would show it' : 'would show it is not'}
              </span>{' '}
              {signpost.text}
            </p>
            {fresh.length ? (
              <ul className="fs-seen">
                {fresh.map((hit) => (
                  <li key={hit.article_id} className={hit.fresh ? 'is-fresh' : ''}>
                    <ItemLink item={hit} ids={ids} /> <span className="muted">{hit.source_name} · {hit.date}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted fs-small">Nothing has matched since {formatDate(signpost.created_at)}.</p>
            )}
            {signpost.seen.some((hit) => hit.earlier) ? (
              <p className="muted fs-small">
                Already in your library when it was made:{' '}
                {signpost.seen.filter((hit) => hit.earlier).map((hit, index) => (
                  <span key={hit.article_id}>
                    {index ? ', ' : ''}
                    <ItemLink item={hit} ids={ids} />
                  </span>
                ))}
              </p>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function OwnConsequence({ foresightId, parent, onAdded, onCancel }) {
  const app = useApp()
  const [text, setText] = useState('')
  const [mechanism, setMechanism] = useState('')
  const [likelihood, setLikelihood] = useState('')
  const [saving, setSaving] = useState(false)
  const save = async () => {
    setSaving(true)
    try {
      const made = await foresightApi.addNode(foresightId, { parent_id: parent?.id ?? null, text, mechanism, likelihood })
      onAdded(made.id)
    } catch (error) {
      app.fail(error)
    } finally {
      setSaving(false)
    }
  }
  return (
    <div className="fs-own">
      <textarea rows={2} value={text} onChange={(event) => setText(event.target.value)} placeholder={parent ? 'What follows from it, in one sentence' : 'A first-order consequence, in one sentence'} autoFocus />
      <input value={mechanism} onChange={(event) => setMechanism(event.target.value)} placeholder="Why it follows (optional)" />
      <select value={likelihood} onChange={(event) => setLikelihood(event.target.value)} aria-label="How likely">
        <option value="">How likely? (optional)</option>
        {LIKELIHOODS.map(([word]) => (
          <option key={word} value={word}>
            {word}
          </option>
        ))}
      </select>
      <div className="fs-own__actions">
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="primary" icon="plus" onClick={save} busy={saving} disabled={!text.trim()}>
          Add
        </Button>
      </div>
    </div>
  )
}

export default function NodePanel({ foresight, node, byId, busy, onStart, onChanged, onSelect, onClose }) {
  const app = useApp()
  const [plan, setPlan] = useState(null)
  const [note, setNote] = useState(node.note || '')
  const [adding, setAdding] = useState(false)
  const kids = foresight.nodes.filter((other) => other.parent_id === node.id)
  const deepest = node.ring >= (foresight.max_ring || 3)

  useEffect(() => {
    setNote(node.note || '')
    setAdding(false)
    setPlan(null)
    if (node.ring < (foresight.max_ring || 3)) {
      foresightApi.plan(node.id).then(setPlan).catch(() => setPlan(null))
    }
  }, [node.id, node.note, node.ring, foresight.max_ring, kids.length])

  const save = async (fields) => {
    try {
      await foresightApi.updateNode(node.id, fields)
      onChanged()
    } catch (error) {
      app.fail(error)
    }
  }
  const remove = async () => {
    const more = kids.length ? ' and what was worked out from it' : ''
    if (!window.confirm(`Remove this consequence${more}?`)) return
    try {
      await foresightApi.removeNode(node.id)
      onClose()
      onChanged()
    } catch (error) {
      app.fail(error)
    }
  }

  const chain = chainOf(node, byId)
  const together = chainChance(node, byId)
  const sourceIds = node.sources.map((source) => source.article_id)
  const status = STATUSES[node.status]

  return (
    <aside className="fs-panel" style={{ '--domain': `var(--fs-${node.domain || 'none'})` }}>
      <div className="fs-panel__head">
        <span className="fs-panel__ring">{RINGS[node.ring]}</span>
        <button type="button" className="fs-panel__close" onClick={onClose} aria-label="Close">
          <Icon name="close" size={16} />
        </button>
      </div>
      {chain.length > 1 ? (
        <ol className="fs-chain">
          {chain.slice(0, -1).map((step) => (
            <li key={step.id}>
              <button type="button" onClick={() => onSelect(step.id)}>
                {step.text}
              </button>
            </li>
          ))}
        </ol>
      ) : null}
      <h3 className="fs-panel__text">{node.text}</h3>
      {node.mechanism ? <p className="fs-panel__why"><strong>Why:</strong> {node.mechanism}</p> : null}
      <div className="fs-panel__facts">
        {node.domain ? <span className="fs-chip fs-chip--domain">{DOMAINS[node.domain]}</span> : null}
        {node.horizon ? <span className="fs-chip">{HORIZONS[node.horizon]}</span> : null}
        <span className="fs-chip" title={BASES[node.basis]?.help}>{BASES[node.basis]?.label}</span>
        {node.dampening ? <span className="fs-chip" title="Pushes back against the other consequences">Pushes back</span> : null}
      </div>
      <label className="fs-panel__likely">
        <span>How likely{node.ring > 1 ? ', if what it follows from happens' : ''}</span>
        <select value={node.likelihood || ''} onChange={(event) => save({ likelihood: event.target.value })}>
          {!node.likelihood ? <option value="">not said</option> : null}
          {LIKELIHOODS.map(([word]) => (
            <option key={word} value={word}>
              {word}
            </option>
          ))}
        </select>
      </label>
      {node.ring > 1 && node.likelihood ? (
        <p className="muted fs-small" title="The likelihoods along the chain, multiplied">
          The whole chain: {wordFor(together)} (about {Math.round(together * 100)}%).
        </p>
      ) : null}
      {status ? (
        <p className={`fs-status fs-status--${status.tone}`}>
          <strong>{status.label}</strong> at the last re-check{node.status_at ? `, ${formatDate(node.status_at)}` : ''}: {node.status_why}
        </p>
      ) : null}

      {node.sources.length ? (
        <div className="fs-panel__block">
          <h4>Rests on</h4>
          <ul className="fs-sources">
            {node.sources.map((source) => (
              <li key={source.article_id}>
                <ItemLink item={source} ids={sourceIds} /> <span className="muted">{source.source_name} · {source.date}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : node.basis === 'reasoning' ? (
        <p className="muted fs-small">No item in your library supports this: it is Claude&rsquo;s reasoning. Its signposts say what would show it.</p>
      ) : null}

      <Signposts node={node} />

      <div className="fs-panel__block">
        <h4>Your note</h4>
        <textarea
          rows={3}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          onBlur={() => (note !== (node.note || '') ? save({ note }) : null)}
          placeholder="What you know about this. Claude reads it when it works out what follows."
        />
        <label className="fs-panel__outcome">
          <span>Looking back</span>
          <select value={node.outcome || ''} onChange={(event) => save({ outcome: event.target.value })}>
            {OUTCOMES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="fs-panel__actions">
        {deepest ? (
          <p className="muted fs-small">A foresight goes three rings deep: beyond that nearly everything is guesswork.</p>
        ) : (
          <Button
            variant="primary"
            icon="sparkles"
            busy={busy}
            disabled={!foresight.ai || !plan?.possible}
            onClick={() => onStart(() => foresightApi.expand(node.id))}
            title={foresight.ai ? undefined : 'Needs an Anthropic API key (Settings)'}
          >
            {kids.length ? 'Work out more of what follows' : 'Work out what follows'}
            {plan?.possible ? ` · reads ${plural(plan.reading, 'item')} · ${aboutPrice(plan.usd)}` : ''}
          </Button>
        )}
        {!deepest && !adding ? (
          <Button icon="plus" onClick={() => setAdding(true)}>
            Add your own
          </Button>
        ) : null}
        <Button variant="ghost" icon="trash" onClick={remove} aria-label="Remove this consequence" disabled={busy} />
      </div>
      {adding ? (
        <OwnConsequence
          foresightId={foresight.id}
          parent={node}
          onCancel={() => setAdding(false)}
          onAdded={(id) => {
            setAdding(false)
            onChanged()
            onSelect(id)
          }}
        />
      ) : null}
      {plan?.possible ? <p className="muted fs-small">With {plan.model_label}.</p> : null}
    </aside>
  )
}

export { OwnConsequence }
