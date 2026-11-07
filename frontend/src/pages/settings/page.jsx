// Settings, in sections with a menu of their own: the API keys, the platform's settings (drawn from the list
// the backend sends, one section per group, so a new setting needs no change here), the scrape log, and an
// overview of the installed plugins.

import { useEffect, useRef, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import JobProgress from '../../components/JobProgress.jsx'
import { Button, Notice, PageHeader, Spinner, Toggle } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { Link } from '../../lib/router.jsx'
import { isActive, useJob } from '../../lib/useJob.js'
import ScrapeLog from './ScrapeLog.jsx'

function ApiKey({ status, onSaved }) {
  const app = useApp()
  const [key, setKey] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async (value) => {
    setSaving(true)
    try {
      await api.settings.saveKey(value)
      setKey('')
      await Promise.all([app.refreshMeta(), onSaved()])
      app.notify(value ? 'API key saved. Claude is connected.' : 'API key removed.')
    } catch (error) {
      app.fail(error)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel__title">
        <h3>
          <Icon name="key" size={17} /> Anthropic API key
        </h3>
        <span className={`badge ${status.available ? 'badge--ok' : 'badge--draft'}`}>
          {status.available ? `Connected ${status.key_hint}` : 'Not connected'}
        </span>
      </div>
      <p className="panel__lead">
        Claude analyses new sources, suggests topic terms, writes briefings and, where you switch it on, labels
        items. Scraping itself never uses the key. Create one at{' '}
        <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
          console.anthropic.com
        </a>
        . It is stored in the platform&rsquo;s <code>.env</code> file, not in the library, and is never shown again.
      </p>
      <form
        className="key-form"
        onSubmit={(event) => {
          event.preventDefault()
          save(key)
        }}
      >
        <input
          type="password"
          className="mono"
          value={key}
          autoComplete="off"
          placeholder={status.available ? 'Paste a new key to replace the current one' : 'sk-ant-…'}
          onChange={(event) => setKey(event.target.value)}
        />
        <Button variant="primary" type="submit" busy={saving} disabled={!key.trim()}>
          Save key
        </Button>
        {status.available ? (
          <Button onClick={() => window.confirm('Remove the API key from this project?') && save('')} disabled={saving}>
            Remove
          </Button>
        ) : null}
      </form>
    </section>
  )
}

const OTHER_KEYS = {
  youtube: {
    title: 'YouTube API key',
    placeholder: 'AIza…',
    about: (
      <>
        Optional. With it a channel can be added by its @name and <em>all</em> of its videos are listed, with their
        length and views; without it only a channel&rsquo;s 15 newest videos can be read. It is free: in the{' '}
        <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noreferrer">
          Google Cloud console
        </a>{' '}
        switch on <em>YouTube Data API v3</em> for a project and create an API key under <em>Credentials</em>. It
        allows 10,000 units a day; a page of fifty videos costs two.
      </>
    ),
  },
  gemini: {
    title: 'Gemini API key',
    placeholder: 'AIza…',
    about: (
      <>
        Needed to turn videos and podcast episodes into articles. YouTube&rsquo;s own API gives a transcript
        only to the owner of a video, and Spotify gives none at all, so what is said is written out by
        Google&rsquo;s Gemini, which can read a public YouTube video and an audio file handed to it; Claude then
        writes the article. Create a key at{' '}
        <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
          aistudio.google.com/apikey
        </a>
        . Google does not charge for reading YouTube videos while that feature is in preview; the free tier reads
        at most eight hours of video a day and Google may use what it is sent to improve its products. The
        audio of a podcast episode is uploaded for the one request and deleted again straight after.
      </>
    ),
  },
}

/** One of the two Google keys videos use. Stored like the Anthropic key: in .env, never shown again. */
function OtherKey({ name }) {
  const app = useApp()
  const about = OTHER_KEYS[name]
  const status = app.meta.keys?.[name] || { set: false, key_hint: '' }
  const [key, setKey] = useState('')
  const [saving, setSaving] = useState(false)
  const save = async (value) => {
    setSaving(true)
    try {
      await api.settings.saveOtherKey(name, value)
      setKey('')
      await app.refreshMeta()
      app.notify(value ? `${about.title} saved.` : `${about.title} removed.`)
    } catch (error) {
      app.fail(error)
    } finally {
      setSaving(false)
    }
  }
  return (
    <section className="panel">
      <div className="panel__title">
        <h3>
          <Icon name="key" size={17} /> {about.title}
        </h3>
        <span className={`badge ${status.set ? 'badge--ok' : 'badge--draft'}`}>
          {status.set ? `Set ${status.key_hint}` : 'Not set'}
        </span>
      </div>
      <p className="panel__lead">{about.about}</p>
      <form
        className="key-form"
        onSubmit={(event) => {
          event.preventDefault()
          save(key)
        }}
      >
        <input
          type="password"
          className="mono"
          value={key}
          autoComplete="off"
          placeholder={status.set ? 'Paste a new key to replace the current one' : about.placeholder}
          onChange={(event) => setKey(event.target.value)}
        />
        <Button variant="primary" type="submit" busy={saving} disabled={!key.trim()}>
          Save key
        </Button>
        {status.set ? (
          <Button onClick={() => window.confirm(`Remove the ${about.title} from this project?`) && save('')} disabled={saving}>
            Remove
          </Button>
        ) : null}
      </form>
    </section>
  )
}

function SettingInput({ spec, value, onChange }) {
  if (spec.type === 'bool') return <Toggle checked={Boolean(value)} onChange={onChange} label={spec.label} />
  if (spec.type === 'select') {
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {spec.choices.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    )
  }
  return (
    <input
      type={spec.type === 'number' ? 'number' : spec.type === 'time' ? 'time' : 'text'}
      min={spec.type === 'number' ? 0 : undefined}
      step="any"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function Plugins() {
  const { meta } = useApp()
  const groups = [
    ['Analyzers', 'How an address becomes a recipe', meta.analyzers],
    ['Connectors', 'How the items of a feed are listed', meta.connectors],
    ['Extractors', 'How one item becomes clean text', meta.extractors],
    ['Fetchers', 'How pages are downloaded', meta.fetchers],
  ]
  return (
    <section className="panel">
      <h3>Installed plugins</h3>
      <p className="panel__lead">
        The platform is built from plugins. Dropping a new file in the matching <code>backend/</code> folder adds
        one; the README explains how.
      </p>
      <div className="plugins">
        {groups.map(([title, about, plugins]) => (
          <div key={title}>
            <h4>{title}</h4>
            <small>{about}</small>
            <ul>
              {plugins.map((plugin) => (
                <li key={plugin.name} title={plugin.description}>
                  <code>{plugin.name}</code> {plugin.label}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  )
}

// The menu of Settings, top to bottom. `group` is the group of settings the backend sends for that section; a
// group not named here (an add-on's) gets a section of its own, above the scrape log.
const SECTIONS = [
  { id: 'keys', label: 'API keys', icon: 'key' },
  { id: 'claude', label: 'Claude', icon: 'sparkles', group: 'Claude' },
  { id: 'videos', label: 'Videos and podcasts', icon: 'play', group: 'Videos' },
  { id: 'scraping', label: 'Scraping', icon: 'refresh', group: 'Scraping' },
  { id: 'meaning', label: 'Search by meaning', icon: 'layers', group: 'Search by meaning' },
  { id: 'log', label: 'Scrape log', icon: 'activity' },
  { id: 'plugins', label: 'Plugins', icon: 'list' },
]

function sectionsFor(spec) {
  const named = new Set(SECTIONS.map((section) => section.group).filter(Boolean))
  const extra = [...new Set(spec.map((item) => item.group))]
    .filter((group) => !named.has(group))
    .map((group) => ({ id: `group-${group.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`, label: group, icon: 'settings', group }))
  const at = SECTIONS.findIndex((section) => section.id === 'log')
  return [...SECTIONS.slice(0, at), ...extra, ...SECTIONS.slice(at)]
}

function Group({ group, spec, values, onChange }) {
  const items = spec.filter((item) => item.group === group)
  if (!items.length) return null
  return (
    <section className="panel">
      <h3>{group}</h3>
      {items.map((item) => (
        <div key={item.key} className="option">
          <div>
            <strong>{item.label}</strong>
            <p>{item.help}</p>
          </div>
          <SettingInput spec={item} value={values[item.key]} onChange={(value) => onChange({ ...values, [item.key]: value })} />
        </div>
      ))}
    </section>
  )
}

function SettingsPage({ params }) {
  const app = useApp()
  const [settings, setSettings] = useState(null)
  const [values, setValues] = useState({})
  const [saving, setSaving] = useState(false)
  const menu = useRef(null)

  const load = () =>
    api.settings
      .get()
      .then((loaded) => {
        setSettings(loaded)
        setValues(loaded.values)
      })
      .catch(app.fail)
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // on a phone the menu is one row that scrolls sideways: keep the open section in sight
  useEffect(() => {
    const row = menu.current
    const active = row?.querySelector('.settings__entry--active')
    if (active && row.scrollWidth > row.clientWidth) row.scrollLeft = active.offsetLeft - row.offsetLeft - 16
  }, [settings, params.section])

  if (!settings) {
    return (
      <div className="boot boot--inline">
        <Spinner size={26} />
      </div>
    )
  }

  const changed = Object.fromEntries(
    Object.entries(values).filter(([key, value]) => String(value) !== String(settings.values[key])),
  )
  const save = async () => {
    setSaving(true)
    try {
      const saved = await api.settings.save(changed)
      setSettings(saved)
      setValues(saved.values)
      await app.refreshMeta() // the prices shown elsewhere depend on the models chosen here
      app.notify('Settings saved.')
    } catch (error) {
      app.fail(error)
    } finally {
      setSaving(false)
    }
  }
  const sections = sectionsFor(settings.spec)
  const section = sections.find((item) => item.id === params.section) || sections[0]
  // which sections hold a change that is not saved yet, so that leaving one does not hide it
  const unsaved = new Set(settings.spec.filter((item) => item.key in changed).map((item) => item.group))

  return (
    <>
      <PageHeader title="Settings" subtitle={`News Scraper Platform ${app.meta.version}`} />
      <div className="settings">
        <nav className="settings__menu" aria-label="Settings" ref={menu}>
          {sections.map((item) => (
            <Link
              key={item.id}
              to={item.id === sections[0].id ? '/settings' : `/settings/${item.id}`}
              className={`settings__entry ${item.id === section.id ? 'settings__entry--active' : ''}`}
            >
              <Icon name={item.icon} size={16} />
              <span>{item.label}</span>
              {item.group && unsaved.has(item.group) ? <span className="settings__dot" title="Not saved yet" /> : null}
            </Link>
          ))}
        </nav>
        <div className="settings__body">
          {section.id === 'keys' ? (
            <>
              <ApiKey status={settings.ai} onSaved={load} />
              <OtherKey name="youtube" />
              <OtherKey name="gemini" />
            </>
          ) : null}
          {section.id === 'meaning' ? <Meaning /> : null}
          {section.group ? <Group group={section.group} spec={settings.spec} values={values} onChange={setValues} /> : null}
          {section.id === 'log' ? <ScrapeLog /> : null}
          {section.id === 'plugins' ? <Plugins /> : null}

          {Object.keys(changed).length ? (
            <div className="wizard__actions wizard__actions--sticky">
              <Button onClick={() => setValues(settings.values)}>Discard</Button>
              <span className="reader__spacer" />
              <Button variant="primary" icon="check" onClick={save} busy={saving}>
                Save settings
              </Button>
            </div>
          ) : null}
        </div>
      </div>
    </>
  )
}

/** Where the embeddings stand, and a button for the ones that are missing. */
function Meaning() {
  const app = useApp()
  const meaning = app.meta.meaning
  const [jobId, setJobId] = useState(null)
  const job = useJob(jobId, () => app.refreshMeta().catch(() => {}))
  const start = async () => {
    try {
      setJobId((await api.meaning.embed()).job_id)
    } catch (error) {
      app.fail(error)
    }
  }
  return (
    <section className="panel">
      <div className="panel__title">
        <h3>
          <Icon name="layers" size={17} /> Understanding by meaning
        </h3>
        <span className="muted">
          {meaning.embedded.toLocaleString()} of {meaning.items.toLocaleString()} items have an embedding
        </span>
        {meaning.available && meaning.pending ? (
          <Button icon="layers" onClick={start} busy={isActive(job)}>
            Embed {meaning.pending.toLocaleString()} items now (free)
          </Button>
        ) : null}
      </div>
      <p className="panel__lead">
        An embedding is a list of numbers that stands for what an item is about. A model that runs with the platform makes
        them after every scrape; nothing is sent anywhere and it costs nothing. Search, topics and &ldquo;More like
        this&rdquo; use them. Until the library holds 50 items they are used more cautiously.
      </p>
      {meaning.reason ? <Notice kind="warn">{meaning.reason}</Notice> : null}
      {jobId ? <JobProgress job={job} compact /> : null}
    </section>
  )
}

export default [
  {
    id: 'settings',
    path: '/settings',
    title: 'Settings',
    icon: 'settings',
    nav: { section: 'platform', order: 2 },
    component: SettingsPage,
  },
  // one section of it: /settings/log, /settings/scraping…
  { id: 'settings-section', path: '/settings/:section', title: 'Settings', icon: 'settings', component: SettingsPage },
]
