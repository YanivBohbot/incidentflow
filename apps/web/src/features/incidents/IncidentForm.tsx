import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Incident } from '../../api'

type IncidentFormProps = {
  onSubmit: (data: Pick<Incident, 'title' | 'description' | 'priority'>) => Promise<void>
}

export function IncidentForm({ onSubmit }: IncidentFormProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState<Incident['priority']>('MEDIUM')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)
    try {
      await onSubmit({ title, description, priority })
      setTitle('')
      setDescription('')
      setPriority('MEDIUM')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form className="incident-form" onSubmit={handleSubmit}>
      <label>What happened?<input minLength={5} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Payment API HTTP 500 errors" required value={title} /></label>
      <label>Observed impact<textarea minLength={10} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the symptoms, affected service, and user impact. This becomes the starting context for the investigation." required rows={5} value={description} /></label>
      <label>Priority<select onChange={(event) => setPriority(event.target.value as Incident['priority'])} value={priority}><option value="LOW">Low</option><option value="MEDIUM">Medium</option><option value="HIGH">High</option><option value="CRITICAL">Critical</option></select></label>
      <button className="primary-button" disabled={isSubmitting} type="submit">{isSubmitting ? 'Saving incident…' : 'Save incident'}</button>
    </form>
  )
}
