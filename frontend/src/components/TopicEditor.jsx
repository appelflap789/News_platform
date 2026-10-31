// Define what a topic collects: a description of what it is about, a list of terms, and optionally names
// that must be mentioned. Claude can propose the lists; they stay editable, and the count updates as you type.

import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { useApp } from '../lib/app.jsx'
import Icon from './Icon.jsx'
import { Usage } from './JobProgress.jsx'
import { Button, Field, Toggle } from './ui.jsx'

const REACHES = [
  ['narrow', 'Narrow: only what is clearly about it'],
  ['balanced', 'Balanced'],
  ['broad', 'Broad: also what is loosely related'],
]

export function ChipInput({ values, onChange, placeholder }) {
  const [draft, setDraft] = useState('')

  const add = (text) => {
    const parts = text.split(/[,\n]/).map((part) => part.trim()).filter(Boolean)
    if (parts.length) onChange([...new Set([...values, ...parts])])
    setDraft('')
  }
  const onKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      add(draft)
    } else if (event.key === 'Backspace' && !draft && values.length) {
      onChange(values.slice(0, -1))
    }
  }

  return (
    <div className="chips-input">
      {values.map((value) => (
        <span key={value} className="term">
          {value}
          <button type="button" onClick={() => onChange(values.filter((v) => v !== value))} aria-label={`Remove ${value}`}>
            <Icon name="close" size={12} />
          </button>
        </span>
      ))}
      <input
        value={draft}
        placeholder={values.length ? '' : placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => add(draft)}
        onPaste={(event) => {
          const text = event.clipboardData.getData('text')
          if (/[,\n]/.test(text)) {
            event.preventDefault()
            add(text)
          }
        }}
      />
    </div>
  )
}

/**
 * Which picture a topic's card on Home shows. `pictures` are the ones of its newest items: left on Automatic
 * the card shows the newest of them and changes with the news; pick one and the card keeps it.
 */
function CoverPicker({ value, pictures, onChange }) {
  const [broken, setBroken] = useState([])
  const offered = [...new Set([value, ...pictures].filter(Boolean))].filter((url) => !broken.includes(url))
  if (!offered.length) return null
  return (
    <div className="field field--wide">
      <span className="field__label">Picture on its card</span>
      <div className="cover-picker">
        <button type="button" className={`cover-picker__auto ${value ? '' : 'is-chosen'}`} aria-pressed={!value} onClick={() => onChange('')}>
          <Icon name="refresh" size={16} />
          Automatic
        </button>
        {offered.map((url) => (
          <button key={url} type="button" className={value === url ? 'is-chosen' : ''} aria-pressed={value === url} aria-label="Use this picture" onClick={() => onChange(url)}>
            <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken((list) => [...list, url])} />
          </button>
        ))}
      </div>
      <span className="field__help">
        On Home a topic is a card. Automatic shows pictures from its newest items, so the card changes with the
        news. Pick one of them to keep that picture instead.
      </span>
    </div>
  )
}

export default function TopicEditor({ value, onChange, withName = true, pictures }) {
  const { meta, fail } = useApp()
  const [suggesting, setSuggesting] = useState(false)
  const [usage, setUsage] = useState(null)
  const [matches, setMatches] = useState(null)
  const ai = meta.ai.available
  const meaning = meta.meaning
  const byMeaning = value.by_meaning !== false

  // live count, shortly after the last edit
  const termsKey = JSON.stringify([value.required_any, value.terms, value.name, value.description, byMeaning, value.reach])
  useEffect(() => {
    const terms = value.terms.length || value.required_any.length ? value.terms : [value.name.trim()].filter(Boolean)
    if (!value.required_any.length && !terms.length) {
      setMatches(null)
      return undefined
    }
    const timer = setTimeout(() => {
      api.topics
        .preview({
          name: value.name || 'preview', description: value.description, required_any: value.required_any, terms,
          by_meaning: byMeaning, reach: value.reach || 'balanced',
        })
        .then(setMatches)
        .catch(() => setMatches(null))
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [termsKey])

  const suggest = async () => {
    setSuggesting(true)
    try {
      const result = await api.topics.expand(value.name.trim())
      setUsage(result.usage)
      onChange({
        ...value,
        description: value.description || result.description,
        required_any: [...new Set([...value.required_any, ...result.required_any])],
        terms: [...new Set([...value.terms, ...result.terms])],
      })
    } catch (error) {
      fail(error)
    } finally {
      setSuggesting(false)
    }
  }

  return (
    <div className="topic-editor">
      {withName ? (
        <Field label="Topic" help="Broad (climate change) or specific (Anduril drone innovation).">
          <input
            autoFocus
            className="input--large"
            value={value.name}
            placeholder="What do you want to follow?"
            onChange={(event) => onChange({ ...value, name: event.target.value })}
          />
        </Field>
      ) : null}

      <div className="topic-editor__suggest">
        <Button variant="primary" icon="sparkles" onClick={suggest} busy={suggesting} disabled={!ai || !value.name.trim()}>
          Suggest terms with Claude
        </Button>
        {ai ? (
          <span className="muted">Adds synonyms, related terms and translations for the languages in your library.</span>
        ) : (
          <span className="muted">Needs an API key (Settings). Without it, type the terms yourself.</span>
        )}
        <Usage usage={usage} />
      </div>

      <Field
        label="About any of"
        help="An article matches when it mentions at least one of these. One word also finds longer forms (drone finds drones); several words must appear together. Press Enter after each term."
      >
        <ChipInput
          values={value.terms}
          onChange={(terms) => onChange({ ...value, terms })}
          placeholder="drone, unmanned aerial, UAV…"
        />
      </Field>
      <Field
        label="Must mention one of (optional)"
        help="For a specific company, person or programme. Leave empty for broad topics."
      >
        <ChipInput
          values={value.required_any}
          onChange={(required_any) => onChange({ ...value, required_any })}
          placeholder="Anduril"
        />
      </Field>
      <Field
        label="What it is about (optional)"
        help="One sentence in plain words, e.g. shipping, attacks and blockades in the Strait of Hormuz. Items are compared with this when the topic also collects by meaning."
      >
        <input value={value.description} onChange={(event) => onChange({ ...value, description: event.target.value })} />
      </Field>

      <div className="topic-editor__meaning">
        <Toggle checked={byMeaning} onChange={(on) => onChange({ ...value, by_meaning: on })} label="Also collect by meaning" />
        <div>
          <strong>Also collect by meaning</strong>
          <p className="muted">
            Adds items that are about the topic without using its terms, also in another language, and sets aside
            the ones that only mention a term in passing.
            {meaning.reason ? ` Not working right now: ${meaning.reason}` : ''}
          </p>
        </div>
        <select
          value={value.reach || 'balanced'}
          disabled={!byMeaning}
          onChange={(event) => onChange({ ...value, reach: event.target.value })}
          aria-label="How close an item has to be"
        >
          {REACHES.map(([reach, label]) => (
            <option key={reach} value={reach}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {pictures ? (
        <CoverPicker value={value.cover_url || ''} pictures={pictures} onChange={(cover_url) => onChange({ ...value, cover_url })} />
      ) : null}

      <p className="topic-editor__count">
        {matches === null
          ? 'Give the topic a name or a term to see how many items it would collect.'
          : `${matches.matches.toLocaleString()} item${matches.matches === 1 ? ' is' : 's are'} about this in your library right now` +
            (matches.by_meaning ? `, ${matches.by_meaning.toLocaleString()} of them found by meaning` : '') +
            (matches.mentions ? `. ${matches.mentions.toLocaleString()} more only mention it.` : '.')}
      </p>
    </div>
  )
}
