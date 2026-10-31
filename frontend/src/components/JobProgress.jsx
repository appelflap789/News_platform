// Live view of a background job: status, the latest step, the log, and what Claude cost.

import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { money } from '../lib/format.js'
import { isActive } from '../lib/useJob.js'
import Icon from './Icon.jsx'
import { Button, Spinner } from './ui.jsx'

const STATUS = {
  queued: 'Waiting to start',
  running: 'Working',
  done: 'Finished',
  error: 'Failed',
  cancelled: 'Cancelled',
}

export function Usage({ usage }) {
  if (!usage || !usage.calls) return null
  return (
    <span className="usage" title={`${usage.input_tokens.toLocaleString()} input and ${usage.output_tokens.toLocaleString()} output tokens in ${usage.calls} call(s). The cost is an estimate.`}>
      <Icon name="sparkles" size={13} />
      {(usage.input_tokens + usage.output_tokens).toLocaleString()} tokens · about {money(usage.estimated_cost_usd)}
    </span>
  )
}

export default function JobProgress({ job, compact = false, startOpen = false }) {
  const [open, setOpen] = useState(startOpen)
  const log = useRef(null)
  const lines = job?.logs || []

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight
  }, [lines.length, open])

  if (!job) {
    return (
      <div className="job">
        <div className="job__head">
          <Spinner /> <span>Starting…</span>
        </div>
      </div>
    )
  }
  const active = isActive(job)
  const last = lines[lines.length - 1]
  const { done, total, label } = job.progress || {}

  return (
    <div className={`job job--${job.status} ${compact ? 'job--compact' : ''}`}>
      <div className="job__head">
        {active ? <Spinner /> : <Icon name={job.status === 'done' ? 'check' : 'alert'} />}
        <div className="job__title">
          <strong>{job.title}</strong>
          <span>
            {STATUS[job.status]}
            {active && label ? ` · ${label}` : ''}
            {!active && job.error ? ` · ${job.error}` : ''}
          </span>
        </div>
        <Usage usage={job.usage} />
        {active ? (
          <Button variant="ghost" icon="stop" onClick={() => api.jobs.cancel(job.id)}>
            Stop
          </Button>
        ) : null}
        <button type="button" className="job__toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? 'Hide log' : 'Show log'}
          <Icon name={open ? 'chevronDown' : 'chevronRight'} size={15} />
        </button>
      </div>
      {active ? (
        <div className="job__bar">
          <span
            className={total ? '' : 'job__bar--endless'}
            style={total ? { width: `${Math.min(100, (done / total) * 100)}%` } : undefined}
          />
        </div>
      ) : null}
      {!open && active && last ? <div className="job__last">{last.msg}</div> : null}
      {open ? (
        <div className="job__log" ref={log}>
          {lines.length === 0 ? <div className="job__line">No steps yet.</div> : null}
          {lines.map((line, index) => (
            <div key={index} className={`job__line job__line--${line.level}`}>
              <time>{new Date(line.t).toLocaleTimeString([], { hour12: false })}</time>
              <span>{line.msg}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
