// The top of Home: a line with what reached the library since you were last here, and the newest topic updates
// as a front page, the newest one large with its picture and the next ones as headlines beside it. The updates
// are the "What is new" texts Claude already wrote for the topics (backend/api/home.py), so this costs nothing.

import { useEffect, useState } from 'react'
import { api } from '../../lib/api.js'
import { hueOf, plural, timeAgo } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'

const SHOWN_TOPICS = 5 // topics named in the "since" line; the rest are counted

/** Opening Home counts as a visit, and then the page asks what is new since the visit before. */
export function useFrontPage() {
  const [front, setFront] = useState(null)
  useEffect(() => {
    let live = true
    api.home
      .visit()
      .catch(() => null)
      .then(() => api.home.get())
      .then((found) => live && setFront(found))
      .catch(() => live && setFront(null)) // an older backend without /api/home: Home as before
    return () => {
      live = false
    }
  }, [])
  return front
}

export function SinceLine({ since, onItems }) {
  if (!since) return null
  const sources = since.sources || []
  const topics = since.topics || []
  const when = `Since you were last here, ${timeAgo(since.at)}`
  if (!since.items) {
    return (
      <p className="since">
        <span className="since__when">{when}:</span> nothing new yet.
      </p>
    )
  }
  return (
    <p className="since">
      <span className="since__when">{when}:</span>{' '}
      <button type="button" className="since__count" onClick={onItems}>
        {plural(since.items, 'new item')}
      </button>{' '}
      <span title={sources.map((source) => `${source.name}: ${source.new}`).join('\n')}>
        from {plural(sources.length, 'source')}
      </span>
      {topics.length ? (
        <>
          <span className="since__dot">·</span>
          {topics.slice(0, SHOWN_TOPICS).map((topic) => (
            <Link key={topic.id} to={`/topics/${topic.id}`} className="since__topic">
              {topic.name} <b>+{topic.new}</b>
            </Link>
          ))}
          {topics.length > SHOWN_TOPICS ? (
            <span className="since__more">and {plural(topics.length - SHOWN_TOPICS, 'more topic')}</span>
          ) : null}
        </>
      ) : null}
    </p>
  )
}

function Lead({ story }) {
  const [broken, setBroken] = useState(false)
  const open = () => navigate(`/topics/${story.topic_id}`)
  const picture = story.image_url && !broken
  return (
    <article className={`front__lead${picture ? '' : ' front__lead--words'}`} role="button" tabIndex={0} onClick={open}
      onKeyDown={(event) => (event.key === 'Enter' ? open() : null)} style={{ '--hue': hueOf(story.topic_name) }}>
      {picture ? (
        <img src={story.image_url} alt="" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
      ) : null}
      <div className="front__shade" />
      <div className="front__words">
        <span className="front__topic">{story.topic_name}</span>
        <h2>{story.headline}</h2>
        {story.standfirst ? <p>{story.standfirst}</p> : null}
        <span className="front__byline">
          From {plural(story.items, 'item')} in {plural(story.sources, 'source')} · {timeAgo(story.written_at)}
        </span>
      </div>
    </article>
  )
}

export function FrontPage({ stories }) {
  if (!stories?.length) return null
  const [lead, ...rest] = stories
  return (
    <section className="front">
      <Lead story={lead} />
      {rest.length ? (
        <ol className="front__list">
          {rest.map((story) => (
            <li key={story.topic_id}>
              <Link to={`/topics/${story.topic_id}`}>
                <span className="front__topic" style={{ '--hue': hueOf(story.topic_name) }}>
                  {story.topic_name}
                </span>
                <strong>{story.headline}</strong>
                <span className="front__byline">{timeAgo(story.written_at)}</span>
              </Link>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  )
}
