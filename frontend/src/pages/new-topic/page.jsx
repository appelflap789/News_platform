// Create a topic: a saved search that becomes its own page in the sidebar.

import { useState } from 'react'
import TopicEditor from '../../components/TopicEditor.jsx'
import { Button, PageHeader } from '../../components/ui.jsx'
import { api } from '../../lib/api.js'
import { useApp } from '../../lib/app.jsx'
import { navigate } from '../../lib/router.jsx'

function NewTopicPage() {
  const app = useApp()
  const [topic, setTopic] = useState({
    name: '', description: '', required_any: [], terms: [], by_meaning: true, reach: 'balanced',
  })
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      const created = await api.topics.create(topic)
      await app.refreshTopics()
      navigate(`/topics/${created.id}`)
    } catch (error) {
      app.fail(error)
      setSaving(false)
    }
  }

  return (
    <div className="wizard">
      <PageHeader
        title="New topic"
        subtitle="A topic collects every matching item from all your sources, and keeps filling as new items are scraped."
      />
      <section className="panel">
        <TopicEditor value={topic} onChange={setTopic} />
        <div className="panel__actions">
          <Button variant="primary" icon="check" onClick={save} busy={saving} disabled={!topic.name.trim()}>
            Create topic
          </Button>
          <span className="muted">Without terms, the topic name itself is used as the search term.</span>
        </div>
      </section>
    </div>
  )
}

export default {
  id: 'new-topic',
  path: '/topics/new',
  title: 'New topic',
  icon: 'plus',
  nav: { section: 'topics', order: 2, action: true },
  component: NewTopicPage,
}
