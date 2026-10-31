// A source's own page, laid out like a channel: who it is, what it has published, how it is built.

import { useCallback, useEffect, useRef, useState } from 'react'
import ArticleGrid from '../../components/ArticleGrid.jsx'
import Icon from '../../components/Icon.jsx'
import JobProgress from '../../components/JobProgress.jsx'
import Markdown from '../../components/Markdown.jsx'
import RecipeEditor, { previewsByKey, stripKeys, withKeys } from '../../components/RecipeEditor.jsx'
import { Avatar, Button, Chip, Empty, Notice, Spinner, Tabs, Toggle } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { aboutPrice, hostOf, hueOf, INTERVALS, plural, roughly, smallPrice, timeAgo } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import { isActive, useJob } from '../../lib/useJob.js'

function Structure({ source, onSaved }) {
  const app = useApp()
  const ai = app.meta.ai.available
  const [draft, setDraft] = useState(null) // the recipe being edited, or null when just viewing
  const [previews, setPreviews] = useState({})
  const [saving, setSaving] = useState(false)
  const [analysisId, setAnalysisId] = useState(null)

  const analysis = useJob(analysisId, (finished) => {
    if (finished.status !== 'done') return
    const keyed = withKeys(finished.result.recipe)
    setDraft(keyed)
    setPreviews(previewsByKey(keyed, finished.result.previews))
    app.notify('Analysis finished. Review the new recipe and save it to start using it.')
  })

  const edit = () => {
    setDraft(withKeys(source.recipe))
    setPreviews({})
  }
  const save = async () => {
    setSaving(true)
    try {
      await api.sources.update(source.id, { recipe: stripKeys(draft) })
      setDraft(null)
      setAnalysisId(null)
      await onSaved()
      app.notify('Recipe saved.')
    } catch (error) {
      app.fail(error)
    } finally {
      setSaving(false)
    }
  }
  const reanalyze = async (analyzer) => {
    try {
      const started = await api.sources.reanalyze(source.id, { url: source.url, analyzer, hint: '' })
      setAnalysisId(started.job_id)
    } catch (error) {
      app.fail(error)
    }
  }

  const recipe = draft || source.recipe
  const connectorLabel = (name) => app.meta.connectors.find((c) => c.name === name)?.label || name

  return (
    <div className="structure">
      <section className="panel report">
        <div className="panel__title">
          <h3>How this source is built</h3>
          {draft ? <span className="badge badge--draft">Unsaved draft</span> : null}
        </div>
        {recipe.structure_report ? (
          <Markdown text={recipe.structure_report} />
        ) : (
          <p className="muted">There is no description of this source&rsquo;s structure.</p>
        )}
      </section>

      {analysisId && (isActive(analysis) || analysis?.status === 'error') ? <JobProgress job={analysis} startOpen /> : null}

      {draft ? (
        <>
          <RecipeEditor recipe={draft} onChange={setDraft} previews={previews} onPreviews={setPreviews} />
          <div className="wizard__actions wizard__actions--sticky">
            <Button onClick={() => setDraft(null)}>Discard changes</Button>
            <span className="reader__spacer" />
            <Button variant="primary" icon="check" onClick={save} busy={saving}>
              Save recipe
            </Button>
          </div>
        </>
      ) : (
        <section className="panel">
          <div className="panel__title">
            <h3>Feeds</h3>
            <span className="muted">What is scraped, and how.</span>
            <Button icon="edit" onClick={edit}>
              Edit recipe
            </Button>
          </div>
          <ul className="feed-list">
            {source.recipe.feeds.map((feed) => (
              <li key={feed.name} className={feed.enabled ? '' : 'is-off'}>
                <Icon name={feed.connector === 'rss' || feed.connector === 'reddit' ? 'rss' : 'list'} size={17} />
                <div>
                  <strong>{feed.name}</strong>
                  <small>
                    {connectorLabel(feed.connector)} · {feed.enabled ? plural(source.feed_counts[feed.name] || 0, 'item') : 'switched off'}
                    {feed.fetch_detail ? '' : ' · listing text only'}
                  </small>
                  <a href={feed.url} target="_blank" rel="noreferrer" className="mono">
                    {feed.url}
                  </a>
                </div>
              </li>
            ))}
            {source.recipe.feeds.length === 0 ? <li className="is-off">This source has no feeds yet.</li> : null}
          </ul>
          <div className="panel__actions">
            <Button icon="sparkles" onClick={() => reanalyze('claude')} disabled={!ai || isActive(analysis)}>
              Analyse again with Claude
            </Button>
            <Button icon="bolt" onClick={() => reanalyze('heuristic')} disabled={isActive(analysis)}>
              Quick detect again
            </Button>
            {!ai ? <span className="muted">Claude analysis needs an API key (Settings).</span> : null}
          </div>
        </section>
      )}
    </div>
  )
}

function SourceSettings({ source, onChanged, onJob, busy }) {
  const app = useApp()
  const ai = app.meta.ai.available

  const update = async (patch) => {
    try {
      await api.sources.update(source.id, patch)
      await onChanged()
    } catch (error) {
      app.fail(error)
    }
  }
  const label = async () => {
    try {
      onJob((await api.sources.enrich(source.id)).job_id)
    } catch (error) {
      app.fail(error)
    }
  }
  const leftOut = source.left_out || { count: 0, recent: [] }
  const videos = source.videos
  const thing = source.kind === 'podcasts' ? 'episode' : 'video'
  const things = `${thing}s`
  const writeVideos = async (retry) => {
    try {
      onJob((await api.sources.videos(source.id, retry)).job_id)
    } catch (error) {
      app.fail(error)
    }
  }
  const tryAgain = async () => {
    try {
      const { forgotten } = await api.sources.forgetLeftOut(source.id)
      app.notify(`The next scrape opens ${plural(forgotten, 'item')} again.`)
      await onChanged()
    } catch (error) {
      app.fail(error)
    }
  }
  const removePartial = async () => {
    const sure = window.confirm(
      `Delete the ${plural(source.partial_stored, 'partial item')} of "${source.name}"? They are the ones of which only a few lines could be read. This cannot be undone.`,
    )
    if (!sure) return
    try {
      const { removed } = await api.sources.removePartial(source.id)
      app.notify(`${plural(removed, 'partial item')} removed.`)
      await Promise.all([onChanged(), app.refreshSources(), app.refreshTopics()])
    } catch (error) {
      app.fail(error)
    }
  }
  const remove = async () => {
    const sure = window.confirm(
      `Delete "${source.name}" and its ${source.article_count.toLocaleString()} stored items? This cannot be undone.`,
    )
    if (!sure) return
    try {
      await api.sources.remove(source.id)
      await Promise.all([app.refreshSources(), app.refreshTopics()])
      app.notify(`${source.name} was deleted.`)
      navigate('/')
    } catch (error) {
      app.fail(error)
    }
  }

  return (
    <div className="structure">
      <section className="panel">
        <h3>Collecting</h3>
        <div className="option">
          <div>
            <strong>Automatic updates</strong>
            <p>How often to look for new items while the platform is running.</p>
          </div>
          <select value={source.interval_minutes} onChange={(event) => update({ interval_minutes: Number(event.target.value) })}>
            {INTERVALS.map(([minutes, text]) => (
              <option key={minutes} value={minutes}>
                {text}
              </option>
            ))}
          </select>
        </div>
        {videos && (source.kind === 'videos' || source.kind === 'podcasts') ? (
          <div className="option">
            <div>
              <strong>Write {things} up as articles</strong>
              {source.kind === 'podcasts' ? (
                <p>
                  Spotify gives out neither the audio nor a transcript of a podcast, so the audio file the
                  show&rsquo;s own feed offers is downloaded and written out by Google&rsquo;s Gemini (
                  {videos.gemini_model}), unless the feed carries the publisher&rsquo;s own transcript.{' '}
                  {videos.model_label} then turns it into an article with headings, a summary and tags, and that
                  article is what search and topics work with. Claude costs about{' '}
                  {smallPrice(videos.per_hour_usd)} for an hour of talking; a run does {videos.per_run} episodes,
                  the newest first, and spends at most {roughly(videos.budget_usd)} (Settings).
                </p>
              ) : (
                <p>
                  What is said in a video is written out by Google&rsquo;s Gemini ({videos.gemini_model}), because
                  YouTube gives a transcript only to a video&rsquo;s owner. {videos.model_label} then turns it into
                  an article with headings, a summary and tags, and that article is what search and topics work
                  with. Claude costs about {smallPrice(videos.per_video_usd)} for twenty minutes of video and{' '}
                  {smallPrice(videos.per_hour_usd)} for an hour; a run does {videos.per_run} videos, the newest
                  first, and spends at most {roughly(videos.budget_usd)} (Settings).
                </p>
              )}
              <p>
                {plural(videos.videos, thing)}: {videos.written} written up
                {videos.to_write_out ? `, ${videos.to_write_out} waiting to be written out` : ''}
                {videos.to_write_up ? `, ${videos.to_write_up} waiting to be written up` : ''}
                {videos.too_long ? `, ${videos.too_long} longer than ${videos.max_minutes} minutes` : ''}
                {videos.failed ? `, ${videos.failed} that could not be written out` : ''}
                {videos.no_audio ? `, ${videos.no_audio} without audio to be had (a show that is only on Spotify)` : ''}.
                {!videos.gemini ? ` There is no Gemini API key yet (Settings), so ${things} keep their description as their text.` : ''}
                {!ai ? ' There is no Anthropic API key (Settings).' : ''}
              </p>
              {source.write_videos && ((videos.gemini && videos.to_write_out > 0) || (ai && videos.to_write_up > 0)) ? (
                <Button icon="play" onClick={() => writeVideos(false)} disabled={busy}>
                  {videos.gemini && videos.to_write_out
                    ? `Do the next ${Math.min(videos.per_run, videos.to_write_out)} of ${videos.to_write_out} waiting ${things}`
                    : `Write up ${plural(videos.to_write_up, thing)} · ${aboutPrice(videos.usd)}`}
                </Button>
              ) : null}
              {source.write_videos && videos.gemini && videos.failed > 0 ? (
                <Button icon="refresh" onClick={() => writeVideos(true)} disabled={busy}>
                  Try the {videos.failed} that could not be read again
                </Button>
              ) : null}
            </div>
            <Toggle
              checked={source.write_videos}
              onChange={(write_videos) => update({ write_videos })}
              label={`Write ${things} up as articles`}
            />
          </div>
        ) : null}
        <div className="option">
          <div>
            <strong>Leave out items behind a login or paywall</strong>
            <p>
              When an item&rsquo;s own page shows only an opening and then asks to log in or subscribe, sends you
              to a login page, or refuses the scraper, the item is not stored. Switched off, such an item is
              stored with the few lines that could be read and marked as partial. It applies to feeds that open
              every item; a feed that stores teasers on purpose is left as it is.
            </p>
            {leftOut.count ? (
              <details className="left-out">
                <summary>{plural(leftOut.count, 'item')} left out so far</summary>
                <ul>
                  {leftOut.recent.map((entry) => (
                    <li key={entry.url}>
                      <a href={entry.url} target="_blank" rel="noreferrer">
                        {entry.title || entry.url}
                      </a>
                      <span>{entry.reason}</span>
                    </li>
                  ))}
                </ul>
                {leftOut.count > leftOut.recent.length ? (
                  <p className="muted">and {(leftOut.count - leftOut.recent.length).toLocaleString()} more.</p>
                ) : null}
                <Button icon="refresh" onClick={tryAgain} disabled={busy}>
                  Try them again at the next scrape
                </Button>
              </details>
            ) : null}
            {source.skip_walled && source.partial_stored > 0 ? (
              <Button icon="trash" onClick={removePartial} disabled={busy}>
                Remove the {plural(source.partial_stored, 'partial item')} stored earlier
              </Button>
            ) : null}
          </div>
          <Toggle
            checked={source.skip_walled}
            onChange={(skip_walled) => update({ skip_walled })}
            label="Leave out items behind a login or paywall"
          />
        </div>
        <div className="option">
          <div>
            <strong>AI summary and tags</strong>
            <p>
              Claude writes a two-sentence summary and topic tags for every new item of this source. The summary
              is in English, also for items in another language (Settings changes that). Costs roughly{' '}
              {roughly(source.labels.low_per_1000_usd)} to {roughly(source.labels.high_per_1000_usd)} per 1,000
              items with {source.labels.model_label}, depending on their length.
              {!ai ? ' Needs an API key (Settings).' : ''}
            </p>
            {source.enrich_enabled && ai && source.pending_enrichment > 0 ? (
              <Button icon="sparkles" onClick={label} disabled={busy}>
                Label the {source.pending_enrichment.toLocaleString()} items already stored
              </Button>
            ) : null}
          </div>
          <Toggle
            checked={source.enrich_enabled}
            onChange={(enrich_enabled) => update({ enrich_enabled })}
            label="AI summary and tags"
            disabled={!ai && !source.enrich_enabled}
          />
        </div>
      </section>

      <section className="panel panel--danger">
        <h3>Delete this source</h3>
        <div className="option">
          <div>
            <p>Removes the source, its recipe and every item collected from it.</p>
          </div>
          <Button variant="danger" icon="trash" onClick={remove} disabled={busy}>
            Delete source
          </Button>
        </div>
      </section>
    </div>
  )
}

/** 90 -> 'about a minute', 1500 -> 'about 25 minutes', 20000 -> 'about 5.6 hours' */
function howLong(seconds) {
  if (seconds < 100) return 'about a minute'
  if (seconds < 5400) return `about ${Math.round(seconds / 60)} minutes`
  return `about ${(seconds / 3600).toFixed(1)} hours`
}

/**
 * How far back a deep scrape should go, asked before it starts: until the source has so many items, or the
 * whole archive. What is stored already is passed without being opened, so a later, larger number goes on
 * where this one stopped.
 */
function HowFar({ source, onGo, onCancel }) {
  const app = useApp()
  const count = source.article_count
  const picks = [50, 100, 250, 500, 1000, 2500, 5000, 10000].filter((number) => number > count).slice(0, 4)
  // the first round number that is a real step further than what there is: 36 -> 100, 99 -> 250
  const suggested = picks.find((number) => number >= count * 1.5 && number >= count + 20) || picks[0] || count + 100
  const [target, setTarget] = useState(String(suggested))
  const wanted = Math.floor(Number(target) || 0)
  const more = wanted - count
  const perItem = app.meta.scrape.seconds_per_item
  const paid = source.enrich_enabled ? ['AI summary and tags'] : []
  return (
    <section className="panel how-far">
      <div className="panel__title">
        <h3>
          <Icon name="layers" size={17} /> How far back?
        </h3>
        <span className="muted">
          {source.name} has {plural(count, 'item')} now. A deep scrape walks back through its archive, newest first;
          what is stored already is passed without being opened.
        </span>
      </div>
      <form
        className="how-far__row"
        onSubmit={(event) => {
          event.preventDefault()
          if (more > 0) onGo(more)
        }}
      >
        <label>
          Go back until it has
          <input
            type="number"
            min={count + 1}
            step="1"
            value={target}
            autoFocus
            onChange={(event) => setTarget(event.target.value)}
            aria-label="Number of items the source should have"
          />
          items
        </label>
        {picks.map((number) => (
          <Chip key={number} active={wanted === number} onClick={() => setTarget(String(number))}>
            {number.toLocaleString()}
          </Chip>
        ))}
      </form>
      <p className="muted how-far__note">
        {more > 0
          ? `That is ${more.toLocaleString()} more, ${howLong(more * perItem)} if every one has a page to open. If the archive holds fewer, it stops when it runs out.`
          : `Enter a number above the ${count.toLocaleString()} it has now.`}
        {paid.length ? ` ${paid.join(' and ')} ${paid.length > 1 ? 'are' : 'is'} switched on for this source: the new items go through that, within what one run may spend on Claude (${roughly(app.meta.translation?.budget_usd ?? 0.5)}, Settings).` : ''}
      </p>
      <div className="how-far__actions">
        <Button variant="primary" icon="layers" disabled={more <= 0} onClick={() => onGo(more)}>
          {more > 0 ? `Collect ${more.toLocaleString()} more` : 'Collect'}
        </Button>
        <Button onClick={() => onGo(0)} title="Walks the whole archive, as far as a deep scrape may go (the built scraper's own limit, or the number of pages in Settings).">
          Everything in the archive
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </section>
  )
}

function SourcePage({ params }) {
  const app = useApp()
  const id = Number(params.id)
  const [source, setSource] = useState(null)
  const [missing, setMissing] = useState(false)
  const [tab, setTab] = useState('items')
  const [howFar, setHowFar] = useState(false) // the question a deep scrape starts with
  const [jobId, setJobId] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const { fail } = app

  const reload = useCallback(async () => {
    try {
      const found = await api.sources.get(id)
      setSource(found)
      if (found.active_job) setJobId(found.active_job)
      return found
    } catch (error) {
      if (error.status === 404) setMissing(true)
      else fail(error)
      return null
    }
  }, [id, fail])

  useEffect(() => {
    reload()
  }, [reload])

  // An item of this source was transcribed and summarised from the reader: what is left has changed.
  const librarySeq = app.library?.seq || 0
  const librarySeen = useRef(librarySeq)
  useEffect(() => {
    if (librarySeq === librarySeen.current) return
    librarySeen.current = librarySeq
    reload()
  }, [librarySeq, reload])

  const job = useJob(jobId, async (finished) => {
    await Promise.all([reload(), app.refreshSources(), app.refreshTopics()])
    setRefresh((n) => n + 1)
    if (finished.status === 'done' && finished.kind === 'scrape') {
      const ranOut = finished.result.limit && !finished.result.reached ? ' The archive has nothing older.' : ''
      app.notify((finished.result.new ? `${plural(finished.result.new, 'new item')} collected.` : ranOut ? 'Nothing more was found.' : 'Already up to date.') + ranOut)
    }
    if (finished.status === 'done' && finished.kind === 'translate') {
      const { translated = 0, left = 0, failed = 0 } = finished.result || {}
      const rest = left + failed
      app.notify(`${plural(translated, 'item')} translated${rest ? `; ${rest} not (the log says why)` : ''}.`)
    }
    if (finished.status === 'done' && finished.kind === 'videos') {
      const written = finished.result?.written_up || 0
      const waiting = finished.result?.waiting || 0
      app.notify(`${written} written up as ${written === 1 ? 'an article' : 'articles'}${waiting ? `; ${waiting} still waiting (the log says why)` : ''}.`)
    }
  })
  const working = isActive(job)

  // show new cards while a scrape is running, without waiting for it to finish
  useEffect(() => {
    if (!working) return undefined
    const timer = setInterval(() => {
      setRefresh((n) => n + 1)
      reload()
    }, 5000)
    return () => clearInterval(timer)
  }, [working, reload])

  const scrape = async (deep, limit = 0) => {
    setHowFar(false)
    try {
      const started = await api.sources.scrape(id, deep, limit)
      setJobId(started.job_id)
      app.refreshSources()
    } catch (error) {
      fail(error)
    }
  }
  // every item of this source that is not in English and not too long to read, in one run
  const translateAll = async () => {
    try {
      const started = await api.sources.translate(id)
      setJobId(started.job_id)
      app.refreshSources()
    } catch (error) {
      fail(error)
    }
  }
  // every video or episode of this source that has not been transcribed and summarised yet, in one run
  const writeAll = async () => {
    try {
      const started = await api.sources.videos(id, false, true)
      setJobId(started.job_id)
      app.refreshSources()
    } catch (error) {
      fail(error)
    }
  }

  if (missing) {
    return (
      <Empty icon="alert" title="This source does not exist">
        It may have been deleted.
      </Empty>
    )
  }
  if (!source) {
    return (
      <div className="boot boot--inline">
        <Spinner size={26} />
      </div>
    )
  }

  const schedule = INTERVALS.find(([minutes]) => minutes === source.interval_minutes)?.[1]
  const hasFeeds = source.recipe.feeds.some((f) => f.enabled)
  // The button that transcribes and summarises everything that is left. `can_write_one` is missing on a
  // platform that has not been restarted since the button was built: it could not do what the button says.
  const waiting = source.videos?.can_write_one && source.kind !== 'articles' ? source.videos : null
  const things = source.kind === 'podcasts' ? 'episode' : 'video'
  const missingKey = !waiting
    ? ''
    : waiting.to_write_out > 0 && !waiting.gemini
      ? 'Add a Gemini API key in Settings first: it is what writes out what is said.'
      : !app.meta.ai.available
        ? 'Add an Anthropic API key in Settings first: Claude writes the articles.'
        : ''
  const writeAllButton =
    waiting && waiting.all > 0 ? (
      <Button
        variant={source.saved ? 'default' : 'primary'}
        icon="sparkles"
        onClick={writeAll}
        disabled={working || Boolean(missingKey)}
        title={
          missingKey ||
          `Writes out what is said in every ${things} that has not been done yet, and writes each one up as an article with a summary. About ${plural(Math.max(1, waiting.all_minutes), 'minute')}, and ${aboutPrice(waiting.all_usd)} for Claude. You can stop it at any time: what is finished is kept.`
        }
      >
        Transcribe and summarise {plural(waiting.all, things)}
      </Button>
    ) : null

  // The button that translates every item of this source that is not in English, the long ones left out
  // (Settings). Which items those are, the platform tells from their words, for nothing. `too_long` is missing
  // on a platform that has not been restarted since the button was built: it would do something else.
  const foreign = source.translation?.waiting?.too_long !== undefined ? source.translation : null
  const noKey = app.meta.ai.available ? '' : 'Add an Anthropic API key in Settings first: Claude translates.'
  const translateButton =
    foreign && foreign.waiting.items > 0 ? (
      <Button
        icon="globe"
        onClick={translateAll}
        disabled={working || Boolean(noKey)}
        title={
          noKey ||
          `${foreign.model_label} translates the title, the summary and the whole text of each, the shortest first; the original is kept. About ${plural(foreign.waiting.minutes, 'minute')}, and ${aboutPrice(foreign.waiting.usd)}. You can stop it at any time: what is finished is kept.`
        }
      >
        Translate {plural(foreign.waiting.items, 'item')}
      </Button>
    ) : null

  return (
    <div className="source">
      <header className="channel" style={{ '--hue': hueOf(source.name) }}>
        <div className="channel__banner" />
        <div className="channel__row">
          <Avatar name={source.name} src={source.icon_url} size={84} />
          <div className="channel__text">
            <h1>{source.name}</h1>
            <p className="channel__meta">
              {source.recipe.homepage || source.url ? (
                <a href={source.recipe.homepage || source.url} target="_blank" rel="noreferrer">
                  {hostOf(source.url || source.recipe.homepage)} <Icon name="external" size={13} />
                </a>
              ) : null}
              <span>{plural(source.article_count, 'item')}</span>
              <span>
                {working ? 'collecting now' : source.last_scraped_at ? `updated ${timeAgo(source.last_scraped_at)}` : 'not scraped yet'}
              </span>
              {source.interval_minutes ? <span>{schedule?.toLowerCase()}</span> : null}
            </p>
            {source.description ? <p className="channel__about">{source.description}</p> : null}
          </div>
          {source.saved ? (
            <div className="channel__actions">
              {writeAllButton}
              {translateButton}
              <Link to="/add" className="button button--primary">
                <Icon name="plus" size={16} />
                <span>Save another</span>
              </Link>
            </div>
          ) : (
            <div className="channel__actions">
              {writeAllButton}
              {translateButton}
              <Button variant={writeAllButton ? 'default' : 'primary'} icon="refresh" onClick={() => scrape(false)} disabled={working || !hasFeeds}>
                Update
              </Button>
              <Button
                icon="layers"
                // a platform that has not been restarted since the question was built can only do all of it
                onClick={() => (app.meta.scrape ? setHowFar(!howFar) : scrape(true))}
                disabled={working || !hasFeeds}
                title="Walk back through the archive, past items that are already stored. You say how far."
              >
                Deep scrape
              </Button>
            </div>
          )}
        </div>
      </header>

      {howFar && !working ? <HowFar source={source} onGo={(limit) => scrape(true, limit)} onCancel={() => setHowFar(false)} /> : null}
      {jobId && job && (working || job.status === 'error') ? <JobProgress job={job} /> : null}
      {writeAllButton && !working ? (
        <p className="channel__waiting">
          {plural(waiting.all, things)} {waiting.all === 1 ? 'has' : 'have'} not been transcribed and summarised yet.{' '}
          {missingKey || `Doing all of them takes about ${plural(Math.max(1, waiting.all_minutes), 'minute')} and costs ${aboutPrice(waiting.all_usd)} for Claude.`}{' '}
          Or open one and do only that one.
        </p>
      ) : null}
      {foreign && (foreign.waiting.items > 0 || foreign.waiting.too_long > 0) && !working ? (
        <p className="channel__waiting">
          {foreign.waiting.items > 0
            ? `${plural(foreign.waiting.items, 'item')} of this source ${foreign.waiting.items === 1 ? 'is' : 'are'} not in English. ${noKey || `Translating ${foreign.waiting.items === 1 ? 'it' : 'them'} with ${foreign.model_label} takes about ${plural(foreign.waiting.minutes, 'minute')} and costs ${aboutPrice(foreign.waiting.usd)}.`}`
            : ''}
          {foreign.waiting.too_long > 0
            ? ` ${plural(foreign.waiting.too_long, 'item')} in another language ${foreign.waiting.too_long === 1 ? 'is' : 'are'} longer than a ${foreign.waiting.max_minutes}-minute read${foreign.waiting.items > 0 ? ' and left out' : ''}: open one to translate only that one.`
            : ''}
        </p>
      ) : null}
      {source.last_error && !working ? (
        <Notice kind="warn">
          The last update had a problem: {source.last_error}. If this keeps happening the site may have changed;
          analyse it again on the Structure tab.
        </Notice>
      ) : null}

      <Tabs
        current={tab}
        onChange={setTab}
        tabs={[
          ['items', 'Items'],
          ['structure', 'Structure'],
          ['settings', 'Settings'],
        ]}
      />

      {tab === 'items' ? (
        <ItemsTab source={source} id={id} refresh={refresh} working={working} hasFeeds={hasFeeds} onScrape={scrape} />
      ) : null}
      {tab === 'structure' ? <Structure source={source} onSaved={reload} /> : null}
      {tab === 'settings' ? (
        <SourceSettings source={source} onChanged={reload} onJob={setJobId} busy={working} />
      ) : null}
    </div>
  )
}

function ItemsTab({ source, id, refresh, working, hasFeeds, onScrape }) {
  const [type, setType] = useState('')
  const types = [...new Set(source.feeds.filter((f) => f.enabled).map((f) => f.content_type))]
  const load = useCallback(
    (page) => api.articles.list({ source_id: id, content_type: type, sort: 'newest', ...page }),
    [id, type],
  )

  return (
    <>
      {types.length > 1 ? (
        <div className="filters">
          <Chip active={!type} onClick={() => setType('')}>
            All
          </Chip>
          {types.map((entry) => (
            <Chip key={entry} active={type === entry} onClick={() => setType(entry)}>
              {entry[0].toUpperCase() + entry.slice(1)}
            </Chip>
          ))}
        </div>
      ) : null}
      <ArticleGrid
        load={load}
        resetKey={type}
        refreshKey={refresh}
        showSource={false}
        empty={
          working ? (
            <Empty icon="clock" title="Collecting…">
              The first items will appear here in a moment.
            </Empty>
          ) : (
            <Empty
              icon="rss"
              title="Nothing collected yet"
              action={
                hasFeeds ? (
                  <Button variant="primary" icon="refresh" onClick={() => onScrape(false)}>
                    Scrape now
                  </Button>
                ) : null
              }
            >
              {hasFeeds
                ? 'This source has a recipe but has not been scraped.'
                : 'This source has no feed switched on. Open the Structure tab to set one up.'}
            </Empty>
          )
        }
      />
    </>
  )
}

export default {
  id: 'source',
  path: '/sources/:id',
  title: 'Source',
  icon: 'rss',
  nav: { section: 'sources', order: 1 },
  navItems: (app) =>
    app.sources.map((source) => ({
      key: `source-${source.id}`,
      to: `/sources/${source.id}`,
      label: source.name,
      avatar: { name: source.name, src: source.icon_url },
      kind: source.kind,
      count: source.article_count,
      busy: Boolean(source.active_job),
    })),
  component: SourcePage,
}
