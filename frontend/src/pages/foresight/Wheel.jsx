// The futures wheel: the signal in the middle and its consequences on rings around it, first order closest.
// A consequence's colour is its domain, its size its likelihood, its outline what it rests on (solid: the
// library; thin: argued in a source; dashed: reasoning; gold: yours). Lines across the wheel are links between
// chains (green reinforces, red dampens). Pointing at a consequence lights up its chain; a click opens it.

import { useMemo, useState } from 'react'
import { BASES, DOMAINS, KINDS, RINGS, chance } from './words.js'

export const RADII = { 1: 215, 2: 350, 3: 460 }
const CENTRE = 100
const LABEL = { 1: { size: 19, chars: 22, lines: 3 }, 2: { size: 16.5, chars: 22, lines: 2 }, 3: { size: 15, chars: 22, lines: 2 } }

/** The part of the plane to show: the rings there are, the next one (empty, as an invitation) and room for the
 * labels, so that a foresight with one ring is shown larger than one with three. */
function view(nodes) {
  const deepest = Math.max(0, ...nodes.map((node) => node.ring))
  const outer = RADII[Math.min(deepest + 1, 3)]
  const reach = deepest ? RADII[deepest] : CENTRE
  const halfWidth = Math.max(outer + 30, reach + 255)
  const halfHeight = Math.max(outer + 30, reach + 115)
  return { deepest, box: `${-halfWidth} ${-halfHeight} ${2 * halfWidth} ${2 * halfHeight}` }
}
const CROWDED = { 2: 18, 3: 16 } // more than this many on a ring: its labels only show for the chain you point at

/** Where each consequence goes: a ring by its order, and an angle within its parent's share of the circle,
 * which is as large as the number of consequences at the end of its chains. */
export function layout(nodes, radii = RADII) {
  const children = new Map()
  for (const node of nodes) {
    const key = node.parent_id ?? 0
    if (!children.has(key)) children.set(key, [])
    children.get(key).push(node)
  }
  const weights = new Map()
  const weight = (node) => {
    if (!weights.has(node.id)) {
      const kids = children.get(node.id) || []
      weights.set(node.id, kids.length ? kids.reduce((sum, kid) => sum + weight(kid), 0) : 1)
    }
    return weights.get(node.id)
  }
  const placed = new Map()
  const place = (list, start, end) => {
    const total = list.reduce((sum, node) => sum + weight(node), 0) || 1
    let at = start
    for (const node of list) {
      const span = ((end - start) * weight(node)) / total
      const angle = at + span / 2
      const r = radii[node.ring] || radii[3]
      placed.set(node.id, { node, angle, r, x: r * Math.cos(angle), y: r * Math.sin(angle) })
      place(children.get(node.id) || [], at, at + span)
      at += span
    }
  }
  const roots = children.get(0) || []
  const total = roots.reduce((sum, node) => sum + weight(node), 0) || 1
  // the first chain's middle at the top
  const start = -Math.PI / 2 - (Math.PI * (roots[0] ? weight(roots[0]) : 1)) / total
  place(roots, start, start + 2 * Math.PI)
  return { placed, children }
}

export function wrap(text, chars, lines) {
  const words = String(text || '').split(/\s+/).filter(Boolean)
  const out = []
  let line = ''
  for (const word of words) {
    if (line && `${line} ${word}`.length > chars) {
      out.push(line)
      line = word
      if (out.length === lines) break
    } else {
      line = line ? `${line} ${word}` : word
    }
  }
  if (out.length < lines && line) out.push(line)
  const used = out.join(' ').split(/\s+/).length
  if (used < words.length && out.length) out[out.length - 1] = `${out[out.length - 1].replace(/[,.;:]$/, '')}…`
  return out
}

const sizeOf = (node) => (node.ring === 1 ? 13 : node.ring === 2 ? 10 : 8.5) + 12 * chance(node.likelihood)

function Label({ spot, size, chars, lines }) {
  const { node, angle, x, y } = spot
  const cos = Math.cos(angle)
  const sin = Math.sin(angle)
  const r = sizeOf(node)
  const anchor = cos > 0.3 ? 'start' : cos < -0.3 ? 'end' : 'middle'
  const text = wrap(node.text, chars, lines)
  const block = (text.length - 1) * size * 1.15
  let lx = x
  let ly
  if (anchor === 'middle') {
    // above or below its consequence, growing away from it
    ly = sin < 0 ? y - r - 8 - block : y + r + 8 + size * 0.8
  } else {
    // beside it, always clear of the dot, a little up or down the way the wheel goes there
    lx = x + (anchor === 'start' ? 1 : -1) * (r + 8)
    ly = y + sin * r * 0.6 - block / 2 + size * 0.35
  }
  return (
    <text className="wheel__label" x={lx} y={ly} textAnchor={anchor} style={{ fontSize: size }}>
      {text.map((line, index) => (
        <tspan key={index} x={lx} dy={index ? size * 1.15 : 0}>
          {line}
        </tspan>
      ))}
    </text>
  )
}

function curve(from, to) {
  const middle = (from.r + to.r) / 2
  const c1 = [middle * Math.cos(from.angle), middle * Math.sin(from.angle)]
  const c2 = [middle * Math.cos(to.angle), middle * Math.sin(to.angle)]
  return `M${from.x},${from.y} C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${to.x},${to.y}`
}

export default function Wheel({ foresight, nodes, links, selected, onSelect }) {
  const [hovered, setHovered] = useState(null)
  const { placed, children } = useMemo(() => layout(nodes), [nodes])
  const byId = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes])
  const perRing = useMemo(() => {
    const counts = {}
    nodes.forEach((node) => {
      counts[node.ring] = (counts[node.ring] || 0) + 1
    })
    return counts
  }, [nodes])

  // the chain of the consequence pointed at (or chosen): where it comes from and what follows from it
  const focus = hovered ?? selected
  const lit = useMemo(() => {
    if (!focus || !byId[focus]) return null
    const ids = new Set()
    let step = byId[focus]
    while (step) {
      ids.add(step.id)
      step = step.parent_id ? byId[step.parent_id] : null
    }
    const down = (id) => (children.get(id) || []).forEach((kid) => {
      ids.add(kid.id)
      down(kid.id)
    })
    down(focus)
    return ids
  }, [focus, byId, children])
  const dim = (id) => lit && !lit.has(id)
  const name = wrap(foresight.name, 14, 3)
  const { deepest, box } = useMemo(() => view(nodes), [nodes])

  return (
    <div className="wheel">
      <svg viewBox={box} role="img" aria-label={`Futures wheel of ${foresight.name}`} onMouseLeave={() => setHovered(null)}>
        <defs>
          <marker id="wheel-arrow-reinforces" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="wheel__arrow wheel__arrow--reinforces" />
          </marker>
          <marker id="wheel-arrow-dampens" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="wheel__arrow wheel__arrow--dampens" />
          </marker>
        </defs>
        {[1, 2, 3].filter((ring) => ring <= deepest + 1).map((ring) => (
          <circle key={ring} className={`wheel__ring ${perRing[ring] ? '' : 'wheel__ring--empty'}`} r={RADII[ring]} />
        ))}

        {nodes.map((node) => {
          const spot = placed.get(node.id)
          const parent = node.parent_id ? placed.get(node.parent_id) : null
          const d = parent
            ? curve(parent, spot)
            : `M${CENTRE * Math.cos(spot.angle)},${CENTRE * Math.sin(spot.angle)} L${spot.x},${spot.y}`
          return <path key={`edge-${node.id}`} d={d} className={`wheel__edge ${dim(node.id) ? 'is-dim' : ''}`} />
        })}

        {links.map((link, index) => {
          const from = placed.get(link.from)
          const to = placed.get(link.to)
          if (!from || !to) return null
          const shown = !lit || (lit.has(link.from) || lit.has(link.to))
          return (
            <path
              key={`link-${index}`}
              d={`M${from.x},${from.y} Q${(from.x + to.x) * 0.18},${(from.y + to.y) * 0.18} ${to.x},${to.y}`}
              className={`wheel__link wheel__link--${link.effect} ${shown ? '' : 'is-dim'}`}
              markerEnd={`url(#wheel-arrow-${link.effect})`}
            >
              <title>{`${link.effect === 'reinforces' ? 'Reinforces' : 'Dampens'}: ${link.why}`}</title>
            </path>
          )
        })}

        <g className="wheel__centre">
          <circle r={CENTRE} />
          <text className="wheel__kind" y={-CENTRE * 0.42 - (name.length - 1) * 9}>
            {(KINDS[foresight.kind]?.label || 'Trend').toUpperCase()}
          </text>
          <text className="wheel__name" y={-(name.length - 1) * 10.5 + 8}>
            {name.map((line, index) => (
              <tspan key={index} x="0" dy={index ? 21 : 0}>
                {line}
              </tspan>
            ))}
          </text>
        </g>

        {nodes.map((node) => {
          const spot = placed.get(node.id)
          const r = sizeOf(node)
          const signs = node.signs || {}
          const status = node.status ? (['strengthened', 'happening'].includes(node.status) ? 'up' : 'down') : ''
          return (
            <g
              key={node.id}
              className={`wheel__node wheel__node--${node.basis} ${selected === node.id ? 'is-selected' : ''} ${dim(node.id) ? 'is-dim' : ''}`}
              transform={`translate(${spot.x},${spot.y})`}
              style={{ '--domain': `var(--fs-${node.domain || 'none'})` }}
              role="button"
              tabIndex={0}
              aria-label={node.text}
              onMouseEnter={() => setHovered(node.id)}
              onFocus={() => setHovered(node.id)}
              onBlur={() => setHovered(null)}
              onClick={() => onSelect(node.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelect(node.id)
                }
              }}
            >
              <title>{`${node.text}\n${DOMAINS[node.domain] || ''} · ${node.likelihood || 'no likelihood'} · ${BASES[node.basis]?.label || ''}`}</title>
              {status ? <circle className={`wheel__status wheel__status--${status}`} r={r + 7} /> : null}
              <circle className="wheel__dot" r={r} />
              {node.dampening ? <path className="wheel__damp" d={`M${-r * 0.5},0 H${r * 0.5}`} /> : null}
              {signs.for || signs.against ? (
                // new items that matched its signposts: green when they would show it, red when they would show it is not
                <g transform={`translate(${r * 0.8},${-r * 0.8})`} className={`wheel__signs wheel__signs--${signs.against ? 'against' : 'for'}`}>
                  <circle r="9" />
                  <text y="3.5">{(signs.for || 0) + (signs.against || 0)}</text>
                </g>
              ) : null}
            </g>
          )
        })}

        {nodes.map((node) => {
          const spot = placed.get(node.id)
          const crowded = (perRing[node.ring] || 0) > (CROWDED[node.ring] || Infinity)
          if (crowded && !(lit && lit.has(node.id))) return null
          if (lit && !lit.has(node.id) && node.ring > 1) return null
          return <Label key={`label-${node.id}`} spot={spot} {...LABEL[node.ring] || LABEL[3]} />
        })}
      </svg>
    </div>
  )
}

/** What the colours, sizes and lines of the wheel mean. */
export function WheelKey({ nodes, links }) {
  const domains = [...new Set(nodes.map((node) => node.domain).filter(Boolean))]
  const bases = [...new Set(nodes.map((node) => node.basis))]
  return (
    <div className="wheel-key">
      {domains.map((domain) => (
        <span key={domain}>
          <i className="wheel-key__dot" style={{ '--domain': `var(--fs-${domain})` }} /> {DOMAINS[domain] || domain}
        </span>
      ))}
      <span className="wheel-key__gap" />
      {bases.map((basis) => (
        <span key={basis} title={BASES[basis]?.help}>
          <i className={`wheel-key__ring wheel-key__ring--${basis}`} /> {BASES[basis]?.label || basis}
        </span>
      ))}
      {nodes.some((node) => node.dampening) ? (
        <span title="A consequence that pushes back against the others: an adaptation, a substitution, a policy or a market response">
          <i className="wheel-key__damp" /> pushes back
        </span>
      ) : null}
      {links.length ? (
        <>
          <span className="wheel-key__gap" />
          <span><i className="wheel-key__line wheel-key__line--reinforces" /> reinforces</span>
          <span><i className="wheel-key__line wheel-key__line--dampens" /> dampens</span>
        </>
      ) : null}
      <span className="wheel-key__gap" />
      <span className="muted">Rings: {Object.values(RINGS).join(', ').toLowerCase()}, from the middle out. Bigger is more likely.</span>
    </div>
  )
}
