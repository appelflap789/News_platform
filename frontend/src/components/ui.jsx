// Small building blocks used on every page.

import { useState } from 'react'
import Icon from './Icon.jsx'
import { hueOf, initials } from '../lib/format.js'

export function Button({ variant = 'default', icon, busy = false, children, className = '', ...rest }) {
  return (
    <button
      type="button"
      className={`button button--${variant} ${className}`}
      disabled={busy || rest.disabled}
      {...rest}
    >
      {busy ? <Spinner size={15} /> : icon ? <Icon name={icon} size={16} /> : null}
      {children ? <span>{children}</span> : null}
    </button>
  )
}

export function Spinner({ size = 18 }) {
  return <span className="spinner" style={{ width: size, height: size }} role="status" aria-label="Working" />
}

/** The round badge of a source: its icon when it loads, otherwise its initials on a colour of its own. */
export function Avatar({ name, src, size = 36 }) {
  const [broken, setBroken] = useState(false)
  const style = { width: size, height: size, fontSize: size * 0.38, '--hue': hueOf(name) }
  return (
    <span className="avatar" style={style}>
      <span className="avatar__initials">{initials(name)}</span>
      {src && !broken ? (
        <img src={src} alt="" referrerPolicy="no-referrer" loading="lazy" onError={() => setBroken(true)} />
      ) : null}
    </span>
  )
}

export function Chip({ active = false, onClick, children, count }) {
  return (
    <button type="button" className={`chip ${active ? 'chip--active' : ''}`} onClick={onClick}>
      {children}
      {count !== undefined ? <span className="chip__count">{count.toLocaleString()}</span> : null}
    </button>
  )
}

export function Tabs({ tabs, current, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([id, label]) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={current === id}
          className={`tab ${current === id ? 'tab--active' : ''}`}
          onClick={() => onChange(id)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export function Empty({ icon = 'layers', title, children, action }) {
  return (
    <div className="empty">
      <div className="empty__icon">
        <Icon name={icon} size={26} />
      </div>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  )
}

export function Field({ label, help, children, wide = false }) {
  return (
    <label className={`field ${wide ? 'field--wide' : ''}`}>
      <span className="field__label">{label}</span>
      {children}
      {help ? <span className="field__help">{help}</span> : null}
    </label>
  )
}

export function Toggle({ checked, onChange, label, disabled = false }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`toggle ${checked ? 'toggle--on' : ''}`}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle__knob" />
    </button>
  )
}

export function PageHeader({ title, subtitle, children }) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {children ? <div className="page-header__actions">{children}</div> : null}
    </header>
  )
}

export function Notice({ kind = 'info', children }) {
  return (
    <div className={`notice notice--${kind}`}>
      <Icon name={kind === 'info' ? 'sparkles' : 'alert'} size={17} />
      <div>{children}</div>
    </div>
  )
}
