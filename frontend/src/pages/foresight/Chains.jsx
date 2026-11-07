// The same consequences as the wheel, as chains read from left to right: a first-order consequence, what
// follows from it, and what follows from that. On a phone the chains read downwards.

import { BASES, DOMAINS, HORIZON_SHORT, STATUSES } from './words.js'

export function NodeCard({ node, selected, onSelect }) {
  const signs = node.signs || {}
  const status = STATUSES[node.status]
  return (
    <button
      type="button"
      className={`fs-node fs-node--${node.basis} ${selected ? 'is-selected' : ''}`}
      style={{ '--domain': `var(--fs-${node.domain || 'none'})` }}
      onClick={() => onSelect(node.id)}
      title={node.mechanism ? `Why: ${node.mechanism}` : undefined}
    >
      <span className="fs-node__top">
        <span className="fs-node__domain">{DOMAINS[node.domain] || 'Consequence'}</span>
        {node.dampening ? <span className="fs-tag">pushes back</span> : null}
        {status ? <span className={`fs-tag fs-tag--${status.tone}`}>{status.label}</span> : null}
        {signs.for ? <span className="fs-tag fs-tag--ok" title="New items that matched a signpost that would show it">{signs.for} matched</span> : null}
        {signs.against ? <span className="fs-tag fs-tag--danger" title="New items that matched a signpost that would show it is not happening">{signs.against} matched against</span> : null}
        {node.outcome === 'happened' ? <span className="fs-tag fs-tag--ok">happened</span> : null}
        {node.outcome === 'did_not' ? <span className="fs-tag fs-tag--danger">did not happen</span> : null}
      </span>
      <span className="fs-node__text">{node.text}</span>
      <span className="fs-node__meta">
        {[node.likelihood, HORIZON_SHORT[node.horizon], BASES[node.basis]?.short].filter(Boolean).join(' · ')}
      </span>
    </button>
  )
}

function Branch({ node, kids, selected, onSelect }) {
  const next = kids.get(node.id) || []
  return (
    <div className={`chain ${next.length ? 'chain--branches' : ''}`}>
      <NodeCard node={node} selected={selected === node.id} onSelect={onSelect} />
      {next.length ? (
        <div className="chain__next">
          {next.map((kid) => (
            <Branch key={kid.id} node={kid} kids={kids} selected={selected} onSelect={onSelect} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export default function Chains({ nodes, selected, onSelect }) {
  const kids = new Map()
  nodes.forEach((node) => {
    const key = node.parent_id ?? 0
    if (!kids.has(key)) kids.set(key, [])
    kids.get(key).push(node)
  })
  return (
    <div className="chains">
      <div className="chains__heads" aria-hidden="true">
        <span>First order</span>
        <span>Second order</span>
        <span>Third order</span>
      </div>
      {(kids.get(0) || []).map((node) => (
        <Branch key={node.id} node={node} kids={kids} selected={selected} onSelect={onSelect} />
      ))}
    </div>
  )
}
