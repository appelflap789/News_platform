// Activity: every analysis, scrape and briefing the platform has run, with its log and Claude cost.

import { useCallback, useEffect, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import JobProgress, { Usage } from '../../components/JobProgress.jsx'
import { Empty, PageHeader, Spinner } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { timeAgo } from '../../lib/format.js'
import { isActive, useJob } from '../../lib/useJob.js'

const KINDS = {
  analyze: 'Analysis', scrape: 'Scrape', enrich: 'AI labels', translate: 'Translation', briefing: 'The long run',
  news: 'What is new', embed: 'Embedding', save: 'Saved link', videos: 'Videos', comments: 'Comments',
}
const ICONS = {
  analyze: 'search', scrape: 'refresh', enrich: 'sparkles', translate: 'globe', briefing: 'file', news: 'bolt',
  embed: 'layers', save: 'download', videos: 'play', comments: 'post',
}

function Details({ jobId }) {
  const job = useJob(jobId)
  return <JobProgress job={job} startOpen />
}

function ActivityPage() {
  const { fail } = useApp()
  const [jobs, setJobs] = useState(null)
  const [open, setOpen] = useState(null)

  const reload = useCallback(() => api.jobs.list().then(setJobs).catch(fail), [fail])
  useEffect(() => {
    reload()
  }, [reload])

  const anyActive = (jobs || []).some(isActive)
  useEffect(() => {
    if (!anyActive) return undefined
    const timer = setInterval(reload, 2000)
    return () => clearInterval(timer)
  }, [anyActive, reload])

  return (
    <>
      <PageHeader title="Activity" subtitle="What the platform has been doing. Open a row to read its log." />
      {jobs === null ? (
        <div className="boot boot--inline">
          <Spinner size={26} />
        </div>
      ) : jobs.length === 0 ? (
        <Empty icon="activity" title="Nothing has run yet">
          Analyses, scrapes and briefings show up here.
        </Empty>
      ) : (
        <ul className="activity">
          {jobs.map((job) => (
            <li key={job.id} className={`activity__row activity__row--${job.status}`}>
              <button type="button" className="activity__head" onClick={() => setOpen(open === job.id ? null : job.id)}>
                <span className="activity__icon">
                  {isActive(job) ? <Spinner size={16} /> : <Icon name={ICONS[job.kind] || 'activity'} size={17} />}
                </span>
                <span className="activity__title">
                  <strong>{job.title}</strong>
                  <small>
                    {KINDS[job.kind] || job.kind} · {job.status}
                    {job.error ? ` · ${job.error}` : ''}
                  </small>
                </span>
                <Usage usage={job.usage} />
                <time>{timeAgo(job.created_at)}</time>
                <Icon name={open === job.id ? 'chevronDown' : 'chevronRight'} size={16} />
              </button>
              {open === job.id ? <Details jobId={job.id} /> : null}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

export default {
  id: 'activity',
  path: '/activity',
  title: 'Activity',
  icon: 'activity',
  nav: { section: 'platform', order: 1 },
  component: ActivityPage,
}
