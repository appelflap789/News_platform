// A foresight as a card, the size of the cards of items and topics. Where they have a picture, it has its own
// wheel in small: every consequence a dot in its domain's colour, so the card grows as the foresight does.

import { useMemo } from 'react'
import Icon from '../../components/Icon.jsx'
import { hueOf, plural, timeAgo } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import { layout } from './Wheel.jsx'
import { KINDS, STANDINGS } from './words.js'

const SMALL = { 1: 150, 2: 250, 3: 335 }

function MiniWheel({ shape }) {
  const { placed } = useMemo(() => layout(shape, SMALL), [shape])
  return (
    <svg className="mini-wheel" viewBox="-370 -370 740 740" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      {[1, 2, 3].map((ring) => (
        <circle key={ring} r={SMALL[ring]} className="mini-wheel__ring" />
      ))}
      {shape.map((node) => {
        const spot = placed.get(node.id)
        const parent = node.parent_id ? placed.get(node.parent_id) : { x: 0, y: 0 }
        return parent ? <line key={`l${node.id}`} x1={parent.x} y1={parent.y} x2={spot.x} y2={spot.y} className="mini-wheel__edge" /> : null
      })}
      <circle r="58" className="mini-wheel__centre" />
      {shape.map((node) => {
        const spot = placed.get(node.id)
        return (
          <circle
            key={node.id}
            cx={spot.x}
            cy={spot.y}
            r={node.ring === 1 ? 22 : node.ring === 2 ? 16 : 12}
            className={`mini-wheel__dot mini-wheel__dot--${node.basis}`}
            style={{ '--domain': `var(--fs-${node.domain || 'none'})` }}
          />
        )
      })}
    </svg>
  )
}

export default function ForesightCard({ foresight }) {
  const open = () => navigate(`/foresight/${foresight.id}`)
  const standing = STANDINGS[foresight.standing]
  const line = foresight.restated || foresight.statement
  return (
    <article
      className="card card--foresight"
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          open()
        }
      }}
    >
      <div className="thumb thumb--foresight" style={{ '--hue': hueOf(foresight.name) }}>
        <MiniWheel shape={foresight.shape} />
        <span className="badge badge--foresight">Foresight</span>
        <span className="thumb__corner">
          {foresight.job_id ? <span className="thumb__tag">Claude is working</span> : null}
          {foresight.fresh ? (
            <span className="thumb__tag thumb__tag--new" title="New items that matched a signpost since you last opened it">
              {foresight.fresh} new {foresight.fresh === 1 ? 'match' : 'matches'}
            </span>
          ) : null}
        </span>
      </div>
      <div className="card__body">
        <span className="topic-mark fs-mark" style={{ '--hue': hueOf(foresight.name) }}>
          <Icon name="foresight" size={17} />
        </span>
        <div className="card__text">
          <h3 className="card__title">{foresight.name}</h3>
          {line ? <p className="card__snippet">{line}</p> : null}
          <div className="card__meta">
            <span>{KINDS[foresight.kind]?.label}</span>
            {standing ? <span className={`fs-tone--${standing.tone}`}>{standing.label}</span> : null}
            <span>{plural(foresight.consequences, 'consequence')}</span>
            {foresight.seen ? <span>{foresight.seen} matched</span> : null}
            {foresight.updated_at ? <span title={`Changed ${foresight.updated_at}`}>{timeAgo(foresight.updated_at)}</span> : null}
          </div>
        </div>
      </div>
    </article>
  )
}

/** The card that makes a new foresight, for an empty shelf. */
export function NewForesightCard() {
  return (
    <Link to="/foresight/new" className="card card--foresight card--new-foresight">
      <div className="thumb thumb--foresight thumb--invite">
        <Icon name="foresight" size={34} />
        <p>Think a trend through: what follows, and what follows from that</p>
      </div>
      <div className="card__body">
        <span className="topic-mark fs-mark">
          <Icon name="plus" size={17} />
        </span>
        <div className="card__text">
          <h3 className="card__title">New foresight</h3>
          <p className="card__snippet">A trend, a weak signal or an event, read against your library.</p>
        </div>
      </div>
    </Link>
  )
}
