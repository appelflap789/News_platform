// The box that saves one page, one YouTube video or one podcast episode by its address, without making a
// source of where it comes from. It is on the Single items page and at the top of Add source.

import { useState } from 'react'
import { api } from '../lib/api.js'
import { useApp } from '../lib/app.jsx'
import { smallPrice } from '../lib/format.js'
import { isActive, useJob } from '../lib/useJob.js'
import Icon from './Icon.jsx'
import JobProgress from './JobProgress.jsx'
import { Button } from './ui.jsx'

/** Whether the platform lists the single items together (one not restarted since they were gathered cannot). */
export function hasSingleItems(app) {
  return typeof app.stats?.saved === 'number'
}

/** What the platform does with what is said in a video, in one sentence, for the two places that offer it. */
export function videoNote(videos) {
  if (!videos) return '' // the platform has not been restarted since videos were added
  return videos.gemini
    ? `What is said in a video is written out by Gemini and then written up as an article by ${videos.model_label}: about ${smallPrice(videos.per_video_usd)} for twenty minutes of video, ${smallPrice(videos.per_hour_usd)} for an hour.`
    : 'A video is stored with its date, length, views and description, and plays in the reader. To have what is said in it written up as an article, add a Gemini API key in Settings first.'
}

/** `here`: the box is on the Single items page, so what is saved shows up below it; `onSaved` is told then. */
export default function SaveLink({ here = false, onSaved }) {
  const app = useApp()
  const [url, setUrl] = useState('')
  const [jobId, setJobId] = useState(null)
  const [starting, setStarting] = useState(false)
  const job = useJob(jobId, async (finished) => {
    if (finished.status !== 'done') return
    setUrl('')
    await app.refreshSources().catch(() => {})
    onSaved?.()
    app.notify(finished.result.partial ? 'Saved, but only partly: the page could not be read in full.' : 'Saved.')
    app.openReader(finished.result.article_id)
  })
  const save = async () => {
    setStarting(true)
    try {
      const started = await api.links.save(url.trim())
      if (started.already) {
        app.notify(started.put_back ? 'You removed this earlier. It is back in your library, as it was.' : 'This is in your library already.')
        if (started.put_back) {
          app.refreshSources().catch(() => {})
          onSaved?.()
        }
        app.openReader(started.article_id)
      } else {
        setJobId(started.job_id)
      }
    } catch (error) {
      app.fail(error)
    } finally {
      setStarting(false)
    }
  }
  const where = here ? (
    'It shows up below, under its kind, and'
  ) : hasSingleItems(app) ? (
    <>
      It goes to <em>Single items</em> in the sidebar and
    </>
  ) : (
    <>
      It goes to <em>Saved articles</em>, <em>Saved videos</em> or <em>Saved podcasts</em> in the sidebar and
    </>
  )
  return (
    <section className="panel">
      <div className="panel__title">
        <h3>
          <Icon name="download" size={17} /> Save one page, video or podcast episode
        </h3>
        <span className="muted">An article, a PDF, a YouTube video or a podcast episode on Spotify, without following where it comes from.</span>
      </div>
      <form
        className="key-form"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        <input
          className="mono"
          value={url}
          spellCheck={false}
          placeholder="https://www.example.org/an-article  or  youtube.com/watch?v=…  or  open.spotify.com/episode/…"
          onChange={(event) => setUrl(event.target.value)}
          aria-label="Address of the page, video or podcast episode"
        />
        <Button variant="primary" type="submit" icon="plus" busy={starting || isActive(job)} disabled={!url.trim()}>
          Save
        </Button>
      </form>
      <p className="muted save-one__note">
        {where} is searched, embedded and matched to your topics like everything else. {videoNote(app.meta.videos)} A
        podcast episode goes the same way: Spotify only says which episode it is, the audio comes from the show&rsquo;s
        own feed.
      </p>
      {jobId && job ? <JobProgress job={job} compact /> : null}
    </section>
  )
}
