// Every signpost of a foresight in one list, by the consequence it belongs to: what the platform watches for
// after every scrape, and what it has seen.

import { formatDate, plural } from '../../lib/format.js'
import { ItemLink } from './NodePanel.jsx'
import { RINGS } from './words.js'

export default function Signposts({ foresight, onSelect }) {
  const watched = foresight.nodes.filter((node) => node.signposts?.length)
  if (!watched.length) {
    return (
      <section className="panel">
        <h3>Signposts</h3>
        <p className="panel__lead">
          None yet. Claude gives every consequence it works out one or two signposts: what a news item would report if
          it were happening, or if it were not.
        </p>
      </section>
    )
  }
  const count = watched.reduce((sum, node) => sum + node.signposts.length, 0)
  return (
    <section className="panel">
      <h3>Signposts</h3>
      <p className="panel__lead">
        The platform watches for {plural(count, 'signpost')} in every item it collects, for free, after every scrape.{' '}
        {foresight.seen
          ? `${plural(foresight.seen, 'item')} matched since they were made${foresight.fresh ? `, ${foresight.fresh} since you last looked` : ''}.`
          : 'Nothing has matched yet.'}{' '}
        A match is an item that may bear on a consequence; Re-check reads the matches and says which way they point.
      </p>
      <div className="fs-board">
        {watched.map((node) => (
          <div key={node.id} className="fs-board__node" style={{ '--domain': `var(--fs-${node.domain || 'none'})` }}>
            <button type="button" className="fs-board__title" onClick={() => onSelect(node.id)}>
              <span className="muted">{RINGS[node.ring]}</span> {node.text}
            </button>
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
                  <p className="fs-terms">
                    {signpost.terms.map((term) => (
                      <span key={term}>{term}</span>
                    ))}
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
                    <p className="muted fs-small">
                      Watching since {formatDate(signpost.created_at)}
                      {signpost.seen.length ? `; ${plural(signpost.seen.length, 'item')} matched that were already in your library` : ''}.
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </section>
  )
}
