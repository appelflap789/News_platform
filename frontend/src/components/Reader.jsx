// The article reader: a panel that slides over the page, so reading never loses your place in a feed.
// Esc closes it; the arrow keys step through the list the article was opened from; Delete removes the item
// from the library and moves on to the next one.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { useApp } from '../lib/app.jsx'
import { TYPE_LABELS, articleDate, clock, formatDate, hostOf, languageName, readingTime, shortDate, smallPrice, timeAgo } from '../lib/format.js'
import { Link } from '../lib/router.jsx'
import { isActive, useJob } from '../lib/useJob.js'
import Icon from './Icon.jsx'
import JobProgress from './JobProgress.jsx'
import Markdown from './Markdown.jsx'
import { Avatar, Button, Notice, Spinner } from './ui.jsx'

/** Which of your topics this item is in. A click puts it in or takes it out; the topic learns from both. */
function InTopics({ articleId }) {
  const { fail, notify, refreshTopics } = useApp()
  const [topics, setTopics] = useState([])
  const load = useCallback(() => api.articles.topics(articleId).then(setTopics).catch(() => setTopics([])), [articleId])
  useEffect(() => {
    load()
  }, [load])
  if (!topics.length) return null

  const toggle = async (topic) => {
    const inside = topic.why && topic.why !== 'mention'
    // Taking back what you said comes first; otherwise a click says the opposite of what is shown.
    const verdict = topic.verdict ? 'none' : inside ? 'out' : 'in'
    try {
      await api.topics.say(topic.id, articleId, verdict)
      notify(verdict === 'in' ? `Added to ${topic.name}.` : verdict === 'out' ? `Taken out of ${topic.name}.` : `${topic.name} decides for itself again.`)
      await Promise.all([load(), refreshTopics()])
    } catch (error) {
      fail(error)
    }
  }
  return (
    <div className="reader__topics">
      <span>Topics</span>
      {topics.map((topic) => {
        const inside = topic.why && topic.why !== 'mention'
        const title = topic.verdict
          ? `You said this ${topic.verdict === 'in' ? 'belongs to' : 'is not about'} ${topic.name}. Click to take that back.`
          : inside
            ? `In ${topic.name}. Click if it is not about this topic.`
            : `Not in ${topic.name}. Click if it belongs there.`
        return (
          <button key={topic.id} type="button" className={`chip ${inside ? 'chip--active' : ''}`} title={title} onClick={() => toggle(topic)}>
            {inside ? <Icon name="check" size={13} /> : null}
            {topic.name}
            {topic.verdict === 'out' ? <Icon name="close" size={13} /> : null}
          </button>
        )
      })}
    </div>
  )
}

/** Items about the same thing, found through their embeddings. */
function MoreLikeThis({ articleId }) {
  const { openReader } = useApp()
  const [items, setItems] = useState([])
  useEffect(() => {
    let current = true
    setItems([])
    api.articles
      .similar(articleId)
      .then((found) => current && setItems(found.items))
      .catch(() => {})
    return () => {
      current = false
    }
  }, [articleId])
  if (!items.length) return null
  const ids = items.map((item) => item.id)
  return (
    <div className="reader__similar">
      <h2>More like this</h2>
      <ul>
        {items.map((item) => (
          <li key={item.id}>
            <button type="button" onClick={() => openReader(item.id, ids)}>
              {item.title}
            </button>
            <span>
              {item.source_name} · {shortDate(articleDate(item))}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * What there is to read of a video or a podcast episode: the article Claude wrote from the transcript, the
 * transcript itself, and the description. Until it has been written up, the description is all there is.
 */
function VideoText({ article, onChanged }) {
  const { meta, fail, notify, libraryChanged } = useApp()
  const written = Boolean(article.written_at)
  const podcast = !article.video_id
  const thing = podcast ? 'episode' : 'video'

  // The button that transcribes and summarises this one, now. Not offered by a platform that has not been
  // restarted since it was built, nor when there is nothing to hear or a key is missing (the notice says which).
  const [jobId, setJobId] = useState(null)
  const job = useJob(jobId, (finished) => {
    if (finished.status === 'done') notify(`Written up as an article: this ${thing}.`)
    libraryChanged() // the page underneath counts what is left, and its card has a summary now
    onChanged()
  })
  const hearable = Boolean(article.video_id || article.audio_url)
  const keys = (article.transcript || meta.keys?.gemini?.set) && meta.ai.available
  const canWrite = Boolean(meta.videos?.can_write_one) && !written && (hearable || article.transcript) && keys
  const start = async () => {
    try {
      setJobId((await api.articles.write(article.id)).job_id)
    } catch (error) {
      fail(error)
    }
  }
  const seconds = 35 + 0.075 * (article.duration_seconds || 1200) // as measured: see pipeline/videos.py
  const takes = article.transcript ? 'a few seconds' : seconds < 90 ? 'about a minute' : `about ${Math.round(seconds / 60)} minutes`
  // What Claude will cost, from the two prices the platform gives (for 20,000 and for 60,000 characters of
  // transcript) and 18 characters for every second of talking.
  const { per_video_usd: low = 0.002, per_hour_usd: high = 0.0033 } = meta.videos || {}
  const chars = (article.transcript ? article.transcript.length : (article.duration_seconds || 1200) * 18)
  const costs = smallPrice(Math.max(0.0005, low + ((high - low) / 40000) * (chars - 20000)))
  const views = [
    written ? ['article', 'Article'] : null,
    article.transcript ? ['transcript', 'Transcript'] : null,
    ['description', 'Description'],
  ].filter(Boolean)
  const [view, setView] = useState(views[0][0])
  const description = written ? article.original_text : article.text
  const lines = (view === 'transcript' ? article.transcript : description).split(/\n+/).filter((line) => line.trim())
  let missing = ''
  const elsewhere = canWrite ? '' : ' The button on its source\u2019s Settings tab does that.'
  if (!written && article.transcript) {
    missing = `What is said in this ${thing} has been written out, but not yet written up as an article.${elsewhere}`
  } else if (!written && article.transcribed_at) {
    missing = `What is said in this ${thing} could not be written out, so its description is shown.${canWrite ? ' You can try again.' : ' Its source\u2019s Settings tab can try again.'}`
  } else if (!written && podcast && !article.audio_url) {
    missing = 'Only the description is shown. No public feed with the audio was found for this episode (its show may be on Spotify only), so there is nothing to write out.'
  } else if (!written) {
    missing = meta.keys?.gemini?.set
      ? `What is said in this ${thing} has not been written out yet, so its description is shown.${elsewhere}`
      : `Only the description is shown. To have what is said in the ${thing} written up as an article, add a Gemini API key in Settings.`
  }
  return (
    <>
      {views.length > 1 ? (
        <div className="reader__views" role="tablist">
          {views.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={view === id} className={`chip ${view === id ? 'chip--active' : ''}`} onClick={() => setView(id)}>
              {label}
            </button>
          ))}
          {view === 'article' ? <span className="muted">written by Claude from the transcript</span> : null}
          {view === 'transcript' ? (
            <span className="muted">
              {podcast && article.transcribed_at === article.fetched_at
                ? 'the publisher\u2019s own transcript, from the show\u2019s feed'
                : 'written out by Gemini; it can mishear'}
            </span>
          ) : null}
        </div>
      ) : null}
      {missing ? <Notice kind="info">{missing}</Notice> : null}
      {canWrite && !isActive(job) ? (
        <div className="reader__write">
          <Button variant="primary" icon="sparkles" onClick={start} disabled={Boolean(jobId) && !job}>
            {article.transcript ? `Summarise this ${thing}` : `Transcribe and summarise this ${thing}`}
          </Button>
          <span className="muted">
            Takes {takes} and costs about {costs} for Claude.
          </span>
        </div>
      ) : null}
      {jobId && job && (isActive(job) || job.status !== 'done') ? <JobProgress job={job} compact /> : null}
      {view === 'article' ? (
        <div className="reader__text reader__text--written">
          <Markdown text={article.text} />
        </div>
      ) : (
        <div className="reader__text">
          {lines.map((line, index) => (
            <p key={index}>{line}</p>
          ))}
        </div>
      )}
    </>
  )
}

/**
 * An item that came from Reddit: its text, and on request what the comments under the post say. The button
 * reads the highest-voted comments and has Claude sum them up; from then on the item has two views, Article
 * and Comments, and the button reads the discussion again.
 */
function WithComments({ article, paragraphs, onChanged }) {
  const { meta, fail, notify } = useApp()
  const summed = Boolean(article.comments_summary)
  const comments = Array.isArray(article.comments) ? article.comments : []
  const [view, setView] = useState('article')
  const [jobId, setJobId] = useState(null)
  const job = useJob(jobId, (finished) => {
    if (finished.status === 'done') {
      setView('comments')
      notify('The comments are summed up.')
    }
    onChanged()
  })
  const start = async () => {
    try {
      setJobId((await api.articles.comments(article.id)).job_id)
    } catch (error) {
      fail(error)
    }
  }
  const working = isActive(job) || (Boolean(jobId) && !job)
  const about = `Reads the ${meta.comments.comments} highest-voted comments under the post on Reddit and has ${meta.comments.model_label} sum up what people think. About ${smallPrice(meta.comments.usd)}; Reddit allows one request a minute, so it may have to wait that long.`
  const button = (label) => (
    <Button
      variant={summed ? 'default' : 'primary'}
      icon="post"
      onClick={start}
      disabled={working || !meta.ai.available}
      title={meta.ai.available ? about : 'Summing up comments needs an Anthropic API key (Settings).'}
    >
      {label}
    </Button>
  )
  return (
    <>
      {summed ? (
        <div className="reader__views" role="tablist">
          {[['article', 'Article'], ['comments', 'Comments']].map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={view === id} className={`chip ${view === id ? 'chip--active' : ''}`} onClick={() => setView(id)}>
              {label}
            </button>
          ))}
          {view === 'comments' ? (
            <span className="muted">
              summed up by Claude from the {comments.length} highest-voted comments on Reddit, {timeAgo(article.comments_at)}
            </span>
          ) : null}
        </div>
      ) : (
        <div className="reader__write">
          {button('Summarise comments')}
          <span className="muted">{meta.ai.available ? about : 'Needs an Anthropic API key (Settings).'}</span>
        </div>
      )}
      {jobId && job && (isActive(job) || job.status !== 'done') ? <JobProgress job={job} compact /> : null}
      {summed && view === 'comments' ? (
        <>
          <div className="reader__text reader__text--written">
            <Markdown text={article.comments_summary} />
          </div>
          <div className="reader__write">
            {button('Read the comments again')}
            <a href={article.discussion_url} target="_blank" rel="noreferrer">
              Open the discussion on Reddit
            </a>
          </div>
          <h2 className="reader__comments-title">The comments it was made from</h2>
          <ol className="reader__comments">
            {comments.map((comment, index) => (
              <li key={index}>
                <strong>u/{comment.author}</strong>
                {comment.text.split(/\n+/).filter((line) => line.trim()).map((line, part) => (
                  <p key={part}>{line}</p>
                ))}
              </li>
            ))}
          </ol>
        </>
      ) : (
        <div className="reader__text">
          {paragraphs.map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </div>
      )}
    </>
  )
}

/**
 * An item that is not in English and has not been translated: the button that has Claude translate this one,
 * now, whatever its length. The platform sends `translation` (what it costs, how long it takes) only for such
 * an item, and not at all when it has not been restarted since the button was built.
 */
function Translate({ article, onChanged }) {
  const { meta, fail, notify, libraryChanged } = useApp()
  const [jobId, setJobId] = useState(null)
  const job = useJob(jobId, (finished) => {
    if (finished.status === 'done') {
      notify(finished.result?.translated ? 'Translated to English.' : 'This one is in English already; nothing was changed.')
    }
    libraryChanged() // the card shows the English title, and the source page counts what is left
    onChanged()
  })
  const start = async () => {
    try {
      setJobId((await api.articles.translate(article.id)).job_id)
    } catch (error) {
      fail(error)
    }
  }
  const working = isActive(job) || (Boolean(jobId) && !job)
  const { usd, seconds, model_label: model } = article.translation
  const from = article.language && article.language !== 'en' ? ` from ${languageName(article.language)}` : ''
  const takes = seconds < 60 ? 'under a minute' : seconds < 90 ? 'about a minute' : `about ${Math.round(seconds / 60)} minutes`
  const about = `${model} translates the title, the summary and the whole text${from}; the original is kept. About ${smallPrice(usd)}, ${takes}.`
  return (
    <>
      <div className="reader__write">
        <Button variant="primary" icon="globe" onClick={start} disabled={working || !meta.ai.available} title={meta.ai.available ? about : 'Translating needs an Anthropic API key (Settings).'}>
          Translate to English
        </Button>
        <span className="muted">{meta.ai.available ? about : 'Needs an Anthropic API key (Settings).'}</span>
      </div>
      {jobId && job && (isActive(job) || job.status !== 'done') ? <JobProgress job={job} compact /> : null}
    </>
  )
}

export default function Reader() {
  const { reader, openReader, closeReader, fail, removeArticle, canRemove, meta, canFavorite, toggleFavorite } = useApp()
  const [article, setArticle] = useState(null)
  const [original, setOriginal] = useState(false) // show a translated item as it was written
  const id = reader?.id
  const ids = reader?.ids || []
  const position = ids.indexOf(id)

  const step = useCallback(
    (delta) => {
      const next = ids[position + delta]
      if (position >= 0 && next !== undefined) openReader(next, ids)
    },
    [ids, position, openReader],
  )

  useEffect(() => {
    if (!id) return undefined
    let current = true
    setArticle(null)
    setOriginal(false)
    api.articles
      .get(id)
      .then((found) => current && setArticle(found))
      .catch((error) => {
        fail(error)
        closeReader()
      })
    return () => {
      current = false
    }
  }, [id, fail, closeReader])

  /** Read the open item again without clearing it first: it was transcribed and summarised just now. */
  const reloadArticle = useCallback(() => {
    if (!id) return
    api.articles
      .get(id)
      .then((found) => setArticle((current) => (current && current.id === found.id ? found : current)))
      .catch(() => {})
  }, [id])

  // Take this item out of the library and go on with the next one of the list (the one before it at the end).
  const removing = useRef(false)
  const remove = useCallback(async () => {
    if (!article || article.id !== id || removing.current) return
    removing.current = true
    const next = position >= 0 ? ids[position + 1] ?? ids[position - 1] : undefined
    const done = await removeArticle(article)
    removing.current = false
    if (!done) return
    if (next === undefined) closeReader()
    else openReader(next, ids.filter((other) => other !== article.id))
  }, [article, id, ids, position, removeArticle, openReader, closeReader])

  useEffect(() => {
    if (!id) return undefined
    const onKey = (event) => {
      if (event.target.closest('input, textarea, select')) return
      if (event.key === 'Escape') closeReader()
      if (event.key === 'ArrowRight') step(1)
      if (event.key === 'ArrowLeft') step(-1)
      if (event.key === 'Delete' && canRemove) remove()
    }
    window.addEventListener('keydown', onKey)
    document.body.classList.add('reading')
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.classList.remove('reading')
    }
  }, [id, closeReader, step, remove, canRemove])

  if (!id) return null
  const tags = article ? article.tags.split(',').map((tag) => tag.trim()).filter(Boolean) : []
  const shown = article && original ? { title: article.original_title, text: article.original_text } : article
  const paragraphs = article ? shown.text.split(/\n+/).filter((line) => line.trim()) : []

  return (
    <div className="reader" role="dialog" aria-modal="true" aria-label="Article">
      <div className="reader__backdrop" onClick={closeReader} />
      <aside className="reader__panel">
        <div className="reader__bar">
          <Button variant="ghost" icon="close" onClick={closeReader} aria-label="Close" />
          {position >= 0 && ids.length > 1 ? (
            <div className="reader__steps">
              <Button variant="ghost" icon="chevronLeft" disabled={position === 0} onClick={() => step(-1)} aria-label="Previous" />
              <span>
                {position + 1} / {ids.length}
              </span>
              <Button variant="ghost" icon="chevronRight" disabled={position === ids.length - 1} onClick={() => step(1)} aria-label="Next" />
            </div>
          ) : null}
          <span className="reader__spacer" />
          {article && canFavorite ? (
            <button
              type="button"
              className={`button button--ghost reader__favorite ${article.favorite_at ? 'is-on' : ''}`}
              onClick={async () => {
                const starred = await toggleFavorite(article)
                if (starred !== null) setArticle((current) => (current?.id === article.id ? { ...current, favorite_at: starred } : current))
              }}
              title={article.favorite_at ? 'In your Favorites. Click to take it out.' : 'Add to Favorites'}
              aria-label={article.favorite_at ? 'Take out of Favorites' : 'Add to Favorites'}
              aria-pressed={Boolean(article.favorite_at)}
            >
              <Icon name="star" size={16} fill={article.favorite_at ? 'currentColor' : 'none'} />
            </button>
          ) : null}
          {article && canRemove ? (
            <Button
              variant="ghost"
              icon="trash"
              onClick={remove}
              title="Remove from your library; scrapes will leave it out (Delete)"
              aria-label="Remove from your library"
            />
          ) : null}
          {article?.pdf_url ? (
            <a className="button button--default" href={article.pdf_url} target="_blank" rel="noreferrer">
              <Icon name="download" size={16} />
              <span>PDF</span>
            </a>
          ) : null}
          {article ? (
            <a className="button button--primary" href={article.url} target="_blank" rel="noreferrer">
              <Icon name="external" size={16} />
              <span>Open original</span>
            </a>
          ) : null}
        </div>

        {!article ? (
          <div className="reader__loading">
            <Spinner size={26} />
          </div>
        ) : (
          <div className="reader__scroll" key={article.id}>
            <article className="reader__article">
              <Link to={`/sources/${article.source_id}`} className="reader__source" onClick={closeReader}>
                <Avatar name={article.source_name} src={article.source_icon} size={40} />
                <span>
                  <strong>{article.source_name}</strong>
                  <small>
                    {[article.feed_name, hostOf(article.url)].filter(Boolean).join(' · ')}
                  </small>
                </span>
              </Link>
              <h1>{shown.title}</h1>
              <div className="reader__meta">
                <span className={`badge badge--${article.content_type}`}>
                  {TYPE_LABELS[article.content_type] || article.content_type}
                </span>
                {article.author ? <span>{article.author}</span> : null}
                <span>{formatDate(articleDate(article))}</span>
                {(article.video_id || article.content_type === 'podcast') && article.duration_seconds ? (
                  <span>{clock(article.duration_seconds)}</span>
                ) : null}
                {article.video_id && article.views ? <span>{article.views.toLocaleString()} views</span> : null}
                {article.word_count > 60 && (!(article.video_id || article.content_type === 'podcast') || article.written_at) ? (
                  <span>{readingTime(article.word_count)}</span>
                ) : null}
              </div>
              {article.video_id ? (
                <div className="reader__player">
                  <iframe
                    src={`https://www.youtube-nocookie.com/embed/${article.video_id}`}
                    title={article.title}
                    allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    referrerPolicy="strict-origin-when-cross-origin"
                    allowFullScreen
                  />
                </div>
              ) : null}

              {article.audio_url ? (
                // the audio file the show's own feed offers: the same one a podcast app would play
                <audio className="reader__audio" controls preload="none" src={article.audio_url}>
                  <a href={article.audio_url}>Listen to the episode</a>
                </audio>
              ) : null}

              {article.ai_summary ? (
                <div className="reader__summary">
                  <span>
                    <Icon name="sparkles" size={14} /> Summary by Claude
                  </span>
                  <p>{article.ai_summary}</p>
                </div>
              ) : null}
              {article.translated_from ? (
                <div className="reader__translated">
                  <Icon name="globe" size={15} />
                  <span>
                    {original
                      ? `This is the original, in ${languageName(article.translated_from)}.`
                      : `Translated from ${languageName(article.translated_from)} by Claude.`}
                  </span>
                  <button type="button" onClick={() => setOriginal(!original)}>
                    {original ? 'Show the translation' : 'Show the original'}
                  </button>
                </div>
              ) : null}
              {article.translation ? <Translate key={article.id} article={article} onChanged={reloadArticle} /> : null}
              {article.is_partial ? (
                <Notice kind="warn">
                  The scraper could not read this item in full (a login, a paywall, or a page that refused it),
                  so only its opening or what the listing said about it is shown here. Use <em>Open original</em>{' '}
                  for the full piece.
                </Notice>
              ) : null}
              {article.image_url && !article.video_id && article.content_type !== 'podcast' ? (
                <img
                  className="reader__image"
                  src={article.image_url}
                  alt=""
                  referrerPolicy="no-referrer"
                  onError={(event) => {
                    event.currentTarget.style.display = 'none'
                  }}
                />
              ) : null}

              {article.video_id || article.content_type === 'podcast' ? (
                // the key makes it start over, on the Article view, once the item has been written up
                <VideoText key={article.written_at} article={article} onChanged={reloadArticle} />
              ) : article.discussion_url && meta?.comments ? (
                // shared on Reddit: the comments under the post can be summed up (not by a platform that has
                // not been restarted since that was built: it sends neither of the two)
                <WithComments article={article} paragraphs={paragraphs} onChanged={reloadArticle} />
              ) : (
                <div className="reader__text">
                  {paragraphs.map((paragraph, index) => (
                    <p key={index}>{paragraph}</p>
                  ))}
                </div>
              )}

              {tags.length ? (
                <div className="reader__tags">
                  {tags.map((tag) => (
                    <span key={tag} className="tag">
                      {tag}
                    </span>
                  ))}
                </div>
              ) : null}
              <InTopics articleId={article.id} />
              <MoreLikeThis articleId={article.id} />
            </article>
          </div>
        )}
      </aside>
    </div>
  )
}
