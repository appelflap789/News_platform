// Add a source in three steps: give an address, let it be analysed, review the recipe and save.
// Sites that have a scraper of their own (backend/scrapers/) skip all that: they are added with one click.

import { useEffect, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import JobProgress, { Usage } from '../../components/JobProgress.jsx'
import Markdown from '../../components/Markdown.jsx'
import RecipeEditor, { previewsByKey, stripKeys, withKeys } from '../../components/RecipeEditor.jsx'
import SaveLink, { videoNote } from '../../components/SaveLink.jsx'
import { Avatar, Button, Field, Notice, PageHeader, Toggle } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { INTERVALS, roughly, smallPrice } from '../../lib/format.js'
import { Link, navigate } from '../../lib/router.jsx'
import { useJob } from '../../lib/useJob.js'

const STEPS = ['Address', 'Analysis', 'Review']
const EXAMPLES = ['warontherocks.com', 'reddit.com/r/drones', 'youtube.com/@CaspianReport', 'www.sipri.org', 'nos.nl']

function Stepper({ current }) {
  return (
    <ol className="stepper">
      {STEPS.map((label, index) => (
        <li key={label} className={index === current ? 'is-current' : index < current ? 'is-done' : ''}>
          <span>{index < current ? <Icon name="check" size={13} /> : index + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  )
}

function BuiltScrapers() {
  const app = useApp()
  const [scrapers, setScrapers] = useState([])
  const [adding, setAdding] = useState(null)
  const [skipWalled, setSkipWalled] = useState(false)

  useEffect(() => {
    api.scrapers.list().then(setScrapers).catch(app.fail)
  }, [app.fail])

  const add = async (scraper) => {
    setAdding(scraper.name)
    try {
      const created = await api.scrapers.add(scraper.name, { skip_walled: skipWalled })
      await app.refreshSources()
      navigate(`/sources/${created.id}`)
    } catch (error) {
      app.fail(error)
      setAdding(null)
    }
  }

  if (scrapers.length === 0) return null
  return (
    <section className="panel">
      <div className="panel__title">
        <h3>Built scrapers</h3>
        <span className="muted">Written for one site, so there is nothing to analyse.</span>
      </div>
      {scrapers.some((scraper) => !scraper.source_id) ? (
        <div className="option">
          <div>
            <strong>Leave out items behind a login or paywall</strong>
            <p>
              Applies to the scraper you add next: items whose own page cannot be read are not stored. You can
              change it later on the source&rsquo;s Settings tab.
            </p>
          </div>
          <Toggle checked={skipWalled} onChange={setSkipWalled} label="Leave out items behind a login or paywall" />
        </div>
      ) : null}
      {scrapers.map((scraper) => (
        <div key={scraper.name} className="option option--scraper">
          <Avatar name={scraper.label} src={scraper.icon_url} />
          <div>
            <strong>{scraper.label}</strong>
            <p>{scraper.description}</p>
          </div>
          {scraper.source_id ? (
            <Button icon="chevronRight" onClick={() => navigate(`/sources/${scraper.source_id}`)}>
              Open
            </Button>
          ) : (
            <Button variant="primary" icon="plus" busy={adding === scraper.name} onClick={() => add(scraper)}>
              Add and scrape
            </Button>
          )}
        </div>
      ))}
    </section>
  )
}

function AddSourcePage({ query }) {
  const app = useApp()
  const ai = app.meta.ai.available
  const [step, setStep] = useState('input') // input | running | failed | review
  const [url, setUrl] = useState(query.url || '')
  const [hint, setHint] = useState('')
  const [analyzer, setAnalyzer] = useState(ai ? 'claude' : 'heuristic')
  const [jobId, setJobId] = useState(null)
  const [result, setResult] = useState(null)
  const [recipe, setRecipe] = useState(null)
  const [previews, setPreviews] = useState({})
  const [enrich, setEnrich] = useState(false)
  const [skipWalled, setSkipWalled] = useState(false)
  const [writeVideos, setWriteVideos] = useState(true)
  const [interval, setIntervalMinutes] = useState(0)
  const [firstLimit, setFirstLimit] = useState('') // how many the first scrape takes; '' = the first listing pages
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)

  const job = useJob(jobId, (finished) => {
    if (finished.status !== 'done') {
      setStep('failed')
      return
    }
    const keyed = withKeys(finished.result.recipe)
    setResult(finished.result)
    setRecipe(keyed)
    // a channel or a podcast can hold hundreds; start with the newest twenty, and let the rest be asked for
    setFirstLimit(keyed.feeds.some((feed) => feed.connector === 'youtube' || feed.connector === 'podcast') ? '20' : '')
    setPreviews(previewsByKey(keyed, finished.result.previews))
    setStep('review')
  })

  const start = async (chosen = analyzer) => {
    setStarting(true)
    try {
      const started = await api.sources.analyze({ url, analyzer: chosen, hint })
      setAnalyzer(chosen)
      setJobId(started.job_id)
      setStep('running')
    } catch (error) {
      app.fail(error)
    } finally {
      setStarting(false)
    }
  }

  const save = async (scrapeNow) => {
    setSaving(true)
    try {
      const created = await api.sources.create({
        url: result.url,
        recipe: stripKeys(recipe),
        analyzer: result.analyzer,
        enrich_enabled: enrich,
        skip_walled: skipWalled,
        write_videos: writeVideos,
        interval_minutes: interval,
        scrape_now: scrapeNow,
        first_limit: Math.max(0, Math.floor(Number(firstLimit) || 0)),
      })
      await app.refreshSources()
      navigate(`/sources/${created.id}`)
    } catch (error) {
      app.fail(error)
      setSaving(false)
    }
  }

  const stepIndex = step === 'input' ? 0 : step === 'review' ? 2 : 1
  const enabledFeeds = recipe ? recipe.feeds.filter((feed) => feed.enabled).length : 0

  return (
    <div className="wizard">
      <PageHeader title="Add a source" subtitle="A news site, a publications archive, an RSS feed, a subreddit, a YouTube channel or a document.">
        <Stepper current={stepIndex} />
      </PageHeader>

      {step === 'input' ? <SaveLink /> : null}
      {step === 'input' ? (
        <form
          className="panel wizard__form"
          onSubmit={(event) => {
            event.preventDefault()
            start()
          }}
        >
          <Field
            label="Address of the source"
            help="Everything it publishes is collected and kept up to date. For a YouTube channel, give its address (youtube.com/@name) or the address of one of its videos. For a podcast, give the Spotify address of the show (open.spotify.com/show/…) and choose Quick detect."
          >
            <input
              autoFocus
              className="input--large mono"
              value={url}
              spellCheck={false}
              placeholder="https://www.example.org/publications"
              onChange={(event) => setUrl(event.target.value)}
            />
          </Field>
          <p className="wizard__examples">
            For example:
            {EXAMPLES.map((example) => (
              <button key={example} type="button" onClick={() => setUrl(example)}>
                {example}
              </button>
            ))}
          </p>

          <Field
            label="What do you want from it? (optional)"
            help="Guides the analysis: “only reports and papers”, “the Dutch-language news”, “everything about defence technology”."
          >
            <textarea rows={2} value={hint} onChange={(event) => setHint(event.target.value)} />
          </Field>

          <div className="field">
            <span className="field__label">How should it be analysed?</span>
            <div className="choices">
              {app.meta.analyzers
                .slice()
                .sort((a, b) => Number(b.requires_ai) - Number(a.requires_ai))
                .map((option) => {
                  const locked = option.requires_ai && !ai
                  return (
                    <button
                      key={option.name}
                      type="button"
                      disabled={locked}
                      className={`choice ${analyzer === option.name ? 'choice--active' : ''}`}
                      onClick={() => setAnalyzer(option.name)}
                    >
                      <Icon name={option.requires_ai ? 'sparkles' : 'bolt'} size={20} />
                      <span>
                        <strong>{option.label}</strong>
                        <small>{option.description}</small>
                        {locked ? <em>Needs an API key</em> : null}
                      </span>
                    </button>
                  )
                })}
            </div>
            {!ai ? (
              <span className="field__help">
                Claude analysis is switched off until you <Link to="/settings">add an Anthropic API key</Link>.
              </span>
            ) : null}
          </div>

          <div className="wizard__actions">
            <Button variant="primary" type="submit" icon="search" busy={starting} disabled={!url.trim()} className="button--large">
              Analyse source
            </Button>
          </div>
        </form>
      ) : null}
      {step === 'input' ? <BuiltScrapers /> : null}

      {step === 'running' || step === 'failed' ? (
        <div className="panel">
          <JobProgress job={job} startOpen />
          {step === 'failed' ? (
            <div className="wizard__actions">
              <Button icon="chevronLeft" onClick={() => setStep('input')}>
                Back
              </Button>
              {analyzer !== 'heuristic' ? (
                <Button icon="bolt" onClick={() => start('heuristic')} busy={starting}>
                  Try Quick detect instead
                </Button>
              ) : null}
            </div>
          ) : (
            <p className="muted wizard__wait">
              {analyzer === 'claude'
                ? 'Claude is opening pages of the site, trying out ways to list its items, and checking the results. This usually takes one to three minutes.'
                : 'Looking for feeds and sitemaps. This takes a few seconds.'}
            </p>
          )}
        </div>
      ) : null}

      {step === 'review' && recipe ? (
        <>
          <section className="panel report">
            <div className="panel__title">
              <h3>How this source is built</h3>
              <span className="muted">
                {app.meta.analyzers.find((a) => a.name === result.analyzer)?.label || result.analyzer}
              </span>
              <Usage usage={result.usage} />
            </div>
            {recipe.structure_report ? (
              <Markdown text={recipe.structure_report} />
            ) : (
              <p className="muted">No description of the structure was produced.</p>
            )}
          </section>

          {enabledFeeds === 0 ? (
            <Notice kind="warn">
              No feed is switched on, so nothing would be scraped. Switch one on, add a feed by hand, or go back
              and analyse again{result.analyzer === 'heuristic' && ai ? ' with Claude' : ''}.
            </Notice>
          ) : null}

          <RecipeEditor recipe={recipe} onChange={setRecipe} previews={previews} onPreviews={setPreviews} />

          <section className="panel">
            <h3>Options</h3>
            {recipe.feeds.some((feed) => feed.connector === 'youtube') ? (
              <div className="option">
                <div>
                  <strong>Write videos up as articles</strong>
                  <p>
                    {videoNote(app.meta.videos)} A run does {app.meta.videos.per_run} videos, the newest first, and
                    spends at most {roughly(app.meta.videos.budget_usd)} on Claude (Settings); the rest of a channel
                    waits for the next run. You can change this later.
                  </p>
                </div>
                <Toggle checked={writeVideos} onChange={setWriteVideos} label="Write videos up as articles" />
              </div>
            ) : null}
            {recipe.feeds.some((feed) => feed.connector === 'podcast') ? (
              <div className="option">
                <div>
                  <strong>Write episodes up as articles</strong>
                  <p>
                    {app.meta.videos.gemini
                      ? `The audio of an episode is downloaded from the show's feed and written out by Gemini; ${app.meta.videos.model_label} then writes it up as an article, about ${smallPrice(app.meta.videos.per_hour_usd)} for an hour of talking.`
                      : 'An episode is stored with its date, length and description, and plays in the reader. To have what is said in it written up as an article, add a Gemini API key in Settings first.'}{' '}
                    A run does {app.meta.videos.podcasts_per_run ?? 5} episodes, the newest first, and spends at most{' '}
                    {roughly(app.meta.videos.budget_usd)} on Claude (Settings); the rest of the show waits for the
                    next run. You can change this later.
                  </p>
                </div>
                <Toggle checked={writeVideos} onChange={setWriteVideos} label="Write episodes up as articles" />
              </div>
            ) : null}
            <div className="option">
              <div>
                <strong>AI summary and tags</strong>
                <p>
                  Claude writes a two-sentence summary and topic tags for every new item, which improves topic
                  matching. The summary is in English, also for items in another language. Costs roughly{' '}
                  {roughly(app.meta.labels.low_per_1000_usd)} to {roughly(app.meta.labels.high_per_1000_usd)} per
                  1,000 items with {app.meta.labels.model_label}. You can switch this on later.
                </p>
              </div>
              <Toggle checked={enrich} onChange={setEnrich} label="AI summary and tags" disabled={!ai} />
            </div>
            <div className="option">
              <div>
                <strong>Leave out items behind a login or paywall</strong>
                <p>
                  When an item&rsquo;s own page shows only an opening and then asks to log in or subscribe, sends
                  you to a login page, or refuses the scraper, the item is not stored. Switched off, such an item
                  is stored with the few lines that could be read and marked as partial. Costs nothing. You can
                  change this later.
                </p>
              </div>
              <Toggle checked={skipWalled} onChange={setSkipWalled} label="Leave out items behind a login or paywall" />
            </div>
            <div className="option">
              <div>
                <strong>How many to collect now</strong>
                <p>
                  The first scrape takes the newest this many
                  {recipe.feeds.some((feed) => feed.connector === 'youtube')
                    ? ' videos'
                    : recipe.feeds.some((feed) => feed.connector === 'podcast')
                      ? ' episodes'
                      : ' items'}
                  . Empty: as many as the first listing pages hold (Settings), which for a YouTube channel with an
                  API key is 150. After that an update only adds what is new, and <em>Deep scrape</em> goes
                  further back, as far as you say.
                </p>
              </div>
              <input
                type="number"
                min="1"
                step="1"
                value={firstLimit}
                placeholder="The first pages"
                onChange={(event) => setFirstLimit(event.target.value)}
                aria-label="How many to collect now"
              />
            </div>
            <div className="option">
              <div>
                <strong>Automatic updates</strong>
                <p>How often to look for new items while the platform is running.</p>
              </div>
              <select value={interval} onChange={(event) => setIntervalMinutes(Number(event.target.value))}>
                {INTERVALS.map(([minutes, label]) => (
                  <option key={minutes} value={minutes}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </section>

          <div className="wizard__actions wizard__actions--sticky">
            <Button icon="chevronLeft" onClick={() => setStep('input')}>
              Back
            </Button>
            <span className="reader__spacer" />
            <Button onClick={() => save(false)} busy={saving} disabled={!recipe.site_name.trim()}>
              Save without scraping
            </Button>
            <Button
              variant="primary"
              icon="check"
              onClick={() => save(true)}
              busy={saving}
              disabled={!recipe.site_name.trim() || enabledFeeds === 0}
            >
              Save and start scraping
            </Button>
          </div>
        </>
      ) : null}
    </div>
  )
}

export default {
  id: 'add-source',
  path: '/add',
  title: 'Add source',
  icon: 'plus',
  nav: { section: 'sources', order: 2, action: true },
  component: AddSourcePage,
}
