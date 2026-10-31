// Pieces every card is built from. A card type combines them in its own way (see ArticleCard.jsx).

import { useState } from 'react'
import Icon from '../components/Icon.jsx'
import { Avatar } from '../components/ui.jsx'
import { TYPE_LABELS, articleDate, clock, hueOf, readingTime, timeAgo } from '../lib/format.js'

const MARK_OPEN = ''
const MARK_CLOSE = ''

/** Search snippet from the backend, with the matched words highlighted. */
export function Snippet({ text }) {
  if (!text) return null
  const parts = text.split(new RegExp(`${MARK_OPEN}(.*?)${MARK_CLOSE}`, 'gs'))
  return (
    <p className="card__snippet">
      {parts.map((part, index) => (index % 2 ? <mark key={index}>{part}</mark> : part))}
    </p>
  )
}

/**
 * The 16:9 picture of a card. Without an image (or when it fails to load) the card shows the opening
 * words on a colour derived from the source, so every card still says something.
 */
export function Thumb({ article, icon, children }) {
  const [broken, setBroken] = useState(false)
  const hasImage = Boolean(article.image_url) && !broken
  const type = article.content_type
  return (
    <div className={`thumb ${hasImage ? '' : 'thumb--text'}`} style={{ '--hue': hueOf(article.source_name) }}>
      {hasImage ? (
        <img
          src={article.image_url}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setBroken(true)}
        />
      ) : (
        <div className="thumb__words">
          {icon ? <Icon name={icon} size={20} /> : null}
          <p>{article.ai_summary || article.summary || article.title}</p>
        </div>
      )}
      <span className={`badge badge--${type}`}>{TYPE_LABELS[type] || type}</span>
      <span className="thumb__corner">
        {article.why === 'meaning' || article.found_by === 'meaning' ? (
          <span className="thumb__tag thumb__tag--meaning" title="Found by what it is about, not by its words">
            by meaning
          </span>
        ) : null}
        {article.translated_from ? (
          <span className="thumb__tag" title="Translated into English by Claude">
            {article.translated_from.toUpperCase()} → EN
          </span>
        ) : null}
        {article.pdf_url ? <span className="thumb__tag">PDF</span> : null}
        {article.video_id || article.content_type === 'podcast' ? (
          article.duration_seconds ? <span className="thumb__tag">{clock(article.duration_seconds)}</span> : null
        ) : article.word_count > 60 ? (
          <span className="thumb__tag">{readingTime(article.word_count)}</span>
        ) : null}
      </span>
      {children}
    </div>
  )
}

export function CardText({ article, showSource, snippet, extra }) {
  return (
    <div className="card__body">
      {showSource ? <Avatar name={article.source_name} src={article.source_icon} size={34} /> : null}
      <div className="card__text">
        <h3 className="card__title">{article.title}</h3>
        {snippet ? <Snippet text={article.snippet} /> : null}
        <div className="card__meta">
          {showSource ? <span>{article.source_name}</span> : null}
          {extra ? <span>{extra}</span> : null}
          <span title={articleDate(article)}>{timeAgo(articleDate(article))}</span>
        </div>
      </div>
    </div>
  )
}

/**
 * The clickable frame of a card. With `onFavorite` it has a star (filled when `favorite`), with `onRemove` a
 * bin that takes the item out of the library. Both sit in the picture's top right corner.
 */
export function CardFrame({ onOpen, onRemove, onFavorite, favorite = false, className = '', children }) {
  const act = (handler) => (event) => {
    event.stopPropagation() // the card itself opens the reader
    handler()
  }
  return (
    <article
      className={`card ${className}`}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen()
        }
      }}
    >
      {children}
      {onFavorite || onRemove ? (
        <span className="card__actions" onKeyDown={(event) => event.stopPropagation()}>
          {onFavorite ? (
            <button
              type="button"
              className={`card__action card__favorite ${favorite ? 'is-on' : ''}`}
              title={favorite ? 'In your Favorites. Click to take it out.' : 'Add to Favorites'}
              aria-label={favorite ? 'Take out of Favorites' : 'Add to Favorites'}
              aria-pressed={favorite}
              onClick={act(onFavorite)}
            >
              <Icon name="star" size={15} fill={favorite ? 'currentColor' : 'none'} />
            </button>
          ) : null}
          {onRemove ? (
            <button
              type="button"
              className="card__action card__remove"
              title="Remove from your library. Scrapes will leave it out."
              aria-label="Remove from your library"
              onClick={act(onRemove)}
            >
              <Icon name="trash" size={15} />
            </button>
          ) : null}
        </span>
      ) : null}
    </article>
  )
}
