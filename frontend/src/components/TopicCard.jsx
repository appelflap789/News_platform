// A topic as a card on Home, drawn like the cards of items: where an item has its picture, a topic has a few
// pictures from its newest items (or the one picture pinned for it), so the card changes with the news.
// A click goes to the topic's page.

import { useState } from 'react'
import { hueOf, plural, timeAgo } from '../lib/format.js'
import { navigate } from '../lib/router.jsx'
import Icon from './Icon.jsx'

export default function TopicCard({ topic }) {
  const [broken, setBroken] = useState([])
  // the platform offers more pictures than fit, so that one that does not load can make way for the next
  const shown = (topic.cover || []).filter((url) => !broken.includes(url)).slice(0, 4)
  const line = topic.news || topic.description
  const open = () => navigate(`/topics/${topic.id}`)
  return (
    <article
      className="card card--topic"
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
      <div
        className={`thumb ${shown.length ? `thumb--mosaic thumb--mosaic-${shown.length}` : 'thumb--text'}`}
        style={{ '--hue': hueOf(topic.name) }}
      >
        {shown.length ? (
          shown.map((url) => (
            <img key={url} src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken((list) => [...list, url])} />
          ))
        ) : (
          <div className="thumb__words">
            <Icon name="topic" size={20} />
            <p>{line || topic.name}</p>
          </div>
        )}
        <span className="badge badge--topic">Topic</span>
        <span className="thumb__corner">
          {topic.trend === 'spiking' ? (
            <span className="thumb__tag" title="Takes up more of your library this week than in the four weeks before">
              spiking
            </span>
          ) : null}
          {topic.new ? (
            <span className="thumb__tag thumb__tag--new" title="New since you last opened the topic">
              {topic.new.toLocaleString()} new
            </span>
          ) : null}
        </span>
      </div>
      <div className="card__body">
        <span className="topic-mark" style={{ '--hue': hueOf(topic.name) }}>
          <Icon name="topic" size={17} />
        </span>
        <div className="card__text">
          <h3 className="card__title">{topic.name}</h3>
          {line && shown.length ? <p className="card__snippet">{line}</p> : null}
          <div className="card__meta">
            <span>{plural(topic.matches, 'item')}</span>
            {topic.latest ? <span title={`The newest item is from ${topic.latest}`}>{timeAgo(topic.latest)}</span> : null}
          </div>
        </div>
      </div>
    </article>
  )
}
