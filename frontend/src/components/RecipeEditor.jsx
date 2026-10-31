// Review and edit a recipe: the source's identity, its feeds (with live samples), and the item-page
// extraction rules. Used by the Add-source wizard and by a source's Structure tab.
//
// The option fields are not hard-coded: they come from /api/meta, where every connector and extractor
// declares what it understands. A new connector therefore gets its form here automatically.

import { useState } from 'react'
import { api } from '../lib/api.js'
import { useApp } from '../lib/app.jsx'
import { TYPE_LABELS, formatDate } from '../lib/format.js'
import Icon from './Icon.jsx'
import { Button, Field, Spinner, Toggle } from './ui.jsx'

let nextKey = 1

/** Give every feed a client-side key, so samples stay attached to a feed while it is renamed. */
export function withKeys(recipe) {
  return { ...recipe, feeds: (recipe.feeds || []).map((feed) => ({ ...feed, _key: `feed-${nextKey++}` })) }
}

export function stripKeys(recipe) {
  return { ...recipe, feeds: recipe.feeds.map(({ _key, ...feed }) => feed) }
}

export function previewsByKey(recipe, previews) {
  return Object.fromEntries(recipe.feeds.map((feed) => [feed._key, (previews || {})[feed.name]]))
}

function OptionField({ field, value, onChange }) {
  const common = { value: value || '', onChange: (event) => onChange(event.target.value) }
  let input
  if (field.type === 'select') {
    input = (
      <select {...common}>
        <option value="">default</option>
        {field.choices.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    )
  } else if (field.type === 'number') {
    input = <input type="number" {...common} />
  } else {
    input = <input type="text" className="mono" spellCheck={false} placeholder="not set" {...common} />
  }
  return (
    <Field label={field.label} help={field.help}>
      {input}
    </Field>
  )
}

function Sample({ preview }) {
  if (!preview) return <p className="sample__note">Not sampled yet. Press Test to see what this feed finds.</p>
  if (preview.loading) {
    return (
      <p className="sample__note">
        <Spinner size={14} /> Fetching a sample from the live site…
      </p>
    )
  }
  if (preview.error) return <p className="sample__note sample__note--error">{preview.error}</p>
  if (!preview.total_items) {
    return <p className="sample__note sample__note--error">The feed was read, but it contains no items.</p>
  }
  return (
    <div className="sample">
      <p className="sample__note">
        Found {preview.total_items} item{preview.total_items === 1 ? '' : 's'} on {preview.pages.length} page
        {preview.pages.length === 1 ? '' : 's'}. First ones:
      </p>
      <ul>
        {preview.items.slice(0, 5).map((item) => (
          <li key={item.url}>
            <time>{formatDate(item.published) || 'no date'}</time>
            <a href={item.url} target="_blank" rel="noreferrer" title={item.url}>
              {item.title || item.url}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

function FeedEditor({ feed, connectors, contentTypes, preview, onChange, onRemove, onTest }) {
  const [open, setOpen] = useState(false)
  const connector = connectors.find((c) => c.name === feed.connector)
  const fields = connector?.fields || []
  const optionsSet = Object.keys(feed.options || {}).length

  const setOption = (key, value) => {
    const options = { ...feed.options }
    if (value === '') delete options[key]
    else options[key] = value
    onChange({ options })
  }
  const setConnector = (name) => {
    const allowed = new Set((connectors.find((c) => c.name === name)?.fields || []).map((f) => f.key))
    const options = Object.fromEntries(Object.entries(feed.options || {}).filter(([key]) => allowed.has(key)))
    onChange({ connector: name, options })
  }

  return (
    <div className={`feed ${feed.enabled ? '' : 'feed--off'}`}>
      <div className="feed__head">
        <Toggle checked={feed.enabled} onChange={(enabled) => onChange({ enabled })} label="Scrape this feed" />
        <input
          className="feed__name"
          value={feed.name}
          onChange={(event) => onChange({ name: event.target.value })}
          aria-label="Feed name"
        />
        <select value={feed.connector} onChange={(event) => setConnector(event.target.value)} aria-label="Connector">
          {connectors.map((c) => (
            <option key={c.name} value={c.name}>
              {c.label}
            </option>
          ))}
        </select>
        <select
          value={feed.content_type}
          onChange={(event) => onChange({ content_type: event.target.value })}
          aria-label="Content type"
        >
          {contentTypes.map((type) => (
            <option key={type} value={type}>
              {TYPE_LABELS[type] || type}
            </option>
          ))}
        </select>
        <Button icon="play" onClick={onTest} busy={preview?.loading}>
          Test
        </Button>
        <Button variant="ghost" icon="trash" onClick={onRemove} aria-label="Remove feed" />
      </div>

      <input
        className="feed__url mono"
        value={feed.url}
        spellCheck={false}
        onChange={(event) => onChange({ url: event.target.value })}
        aria-label="Feed address"
      />
      {connector ? <p className="feed__about">{connector.description}</p> : null}

      <button type="button" className="disclosure" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={15} />
        Connector settings
        <span>{optionsSet ? `${optionsSet} set` : 'defaults'}</span>
      </button>
      {open ? (
        <div className="feed__options">
          {fields.map((field) => (
            <OptionField
              key={field.key}
              field={field}
              value={feed.options?.[field.key]}
              onChange={(value) => setOption(field.key, value)}
            />
          ))}
          <label className="check">
            <input
              type="checkbox"
              checked={feed.fetch_detail}
              onChange={(event) => onChange({ fetch_detail: event.target.checked })}
            />
            <span>
              Open each item&rsquo;s own page for the full text
              <small>Switch off when the listing already carries the complete item, or item pages are blocked.</small>
            </span>
          </label>
        </div>
      ) : null}

      <Sample preview={preview} />
    </div>
  )
}

function ArticleRules({ recipe, onChange, sampleUrl }) {
  const { meta, fail } = useApp()
  const [open, setOpen] = useState(Object.keys(recipe.article || {}).length > 0)
  const [result, setResult] = useState(null)
  const [testing, setTesting] = useState(false)

  const setRule = (key, value) => {
    const article = { ...recipe.article }
    if (value === '') delete article[key]
    else article[key] = value
    onChange({ ...recipe, article })
  }
  const test = async () => {
    setTesting(true)
    try {
      setResult(await api.recipes.testArticle(sampleUrl, recipe.article || {}))
    } catch (error) {
      setResult(null)
      fail(error)
    } finally {
      setTesting(false)
    }
  }

  return (
    <section className="panel">
      <button type="button" className="disclosure disclosure--title" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={16} />
        Item page extraction
        <span>{Object.keys(recipe.article || {}).length ? 'custom selectors' : 'automatic'}</span>
      </button>
      {open ? (
        <>
          <p className="panel__lead">
            Title, date, author and text of each item page are detected automatically. Set a selector only for
            what comes out wrong.
          </p>
          <div className="feed__options">
            {meta.article_fields.map((field) => (
              <OptionField
                key={field.key}
                field={field}
                value={recipe.article?.[field.key]}
                onChange={(value) => setRule(field.key, value)}
              />
            ))}
          </div>
          <div className="panel__actions">
            <Button icon="play" onClick={test} busy={testing} disabled={!sampleUrl}>
              Test on a sample item
            </Button>
            {!sampleUrl ? <span className="muted">Test a feed first to get a sample item.</span> : null}
          </div>
          {result ? (
            <dl className="extract">
              <dt>Title</dt>
              <dd>{result.title || '—'}</dd>
              <dt>Date</dt>
              <dd>{formatDate(result.published) || '—'}</dd>
              <dt>Author</dt>
              <dd>{result.author || '—'}</dd>
              <dt>PDF</dt>
              <dd>{result.pdf_url || '—'}</dd>
              <dt>Text</dt>
              <dd>
                {result.text_characters.toLocaleString()} characters. {result.text_start}
              </dd>
            </dl>
          ) : null}
        </>
      ) : null}
    </section>
  )
}

export default function RecipeEditor({ recipe, onChange, previews, onPreviews }) {
  const { meta } = useApp()

  const patchFeed = (key, patch) =>
    onChange({ ...recipe, feeds: recipe.feeds.map((feed) => (feed._key === key ? { ...feed, ...patch } : feed)) })
  const removeFeed = (key) => onChange({ ...recipe, feeds: recipe.feeds.filter((feed) => feed._key !== key) })
  const addFeed = () =>
    onChange({
      ...recipe,
      feeds: [
        ...recipe.feeds,
        {
          _key: `feed-${nextKey++}`, name: `Feed ${recipe.feeds.length + 1}`, connector: 'rss',
          url: recipe.homepage || '', content_type: 'article', enabled: true, fetch_detail: true,
          fetcher: 'http', options: {},
        },
      ],
    })
  const testFeed = async (feed) => {
    onPreviews((current) => ({ ...current, [feed._key]: { loading: true } }))
    const { _key, ...payload } = feed
    try {
      const preview = await api.recipes.testFeed(payload)
      onPreviews((current) => ({ ...current, [_key]: preview }))
    } catch (error) {
      onPreviews((current) => ({ ...current, [_key]: { error: error.message } }))
    }
  }

  const sampleUrl = recipe.feeds
    .map((feed) => previews[feed._key]?.items?.[0]?.url)
    .find(Boolean)

  return (
    <div className="recipe">
      <section className="panel">
        <h3>Source</h3>
        <div className="recipe__identity">
          <Field label="Name">
            <input value={recipe.site_name} onChange={(event) => onChange({ ...recipe, site_name: event.target.value })} />
          </Field>
          <Field label="Language">
            <input
              value={recipe.language}
              maxLength={5}
              placeholder="en"
              onChange={(event) => onChange({ ...recipe, language: event.target.value })}
            />
          </Field>
          <Field label="Description" wide>
            <textarea
              rows={2}
              value={recipe.description}
              onChange={(event) => onChange({ ...recipe, description: event.target.value })}
            />
          </Field>
        </div>
      </section>

      <section className="panel">
        <div className="panel__title">
          <h3>Feeds</h3>
          <span className="muted">Each feed is one stream of items from this source.</span>
          <Button icon="plus" onClick={addFeed}>
            Add feed
          </Button>
        </div>
        {recipe.feeds.length === 0 ? (
          <p className="sample__note sample__note--error">
            No feed yet, so there is nothing to scrape. Add one by hand, or analyse the source again.
          </p>
        ) : null}
        {recipe.feeds.map((feed) => (
          <FeedEditor
            key={feed._key}
            feed={feed}
            connectors={meta.connectors}
            contentTypes={meta.content_types}
            preview={previews[feed._key]}
            onChange={(patch) => patchFeed(feed._key, patch)}
            onRemove={() => removeFeed(feed._key)}
            onTest={() => testFeed(feed)}
          />
        ))}
      </section>

      <ArticleRules recipe={recipe} onChange={onChange} sampleUrl={sampleUrl} />
    </div>
  )
}
