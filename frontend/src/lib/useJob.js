// Follow a background job (analysis, scrape, briefing) until it ends.

import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'

export const isActive = (job) => Boolean(job) && (job.status === 'queued' || job.status === 'running')

/** Polls the job and calls onFinish(job) once, when it is done, failed or cancelled. */
export function useJob(jobId, onFinish) {
  const [job, setJob] = useState(null)
  const finish = useRef(onFinish)
  finish.current = onFinish

  useEffect(() => {
    if (!jobId) {
      setJob(null)
      return undefined
    }
    let stopped = false
    let timer
    const tick = async () => {
      try {
        const latest = await api.jobs.get(jobId)
        if (stopped) return
        setJob(latest)
        if (isActive(latest)) {
          timer = setTimeout(tick, 900)
        } else if (finish.current) {
          finish.current(latest)
        }
      } catch {
        if (!stopped) timer = setTimeout(tick, 2500)
      }
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [jobId])

  return job
}
