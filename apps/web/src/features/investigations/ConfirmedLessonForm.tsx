import { useState } from 'react'
import type { IncidentLesson, IncidentLessonConfirmation, Investigation } from '../../api'

type ConfirmedLessonFormProps = {
  investigation: Investigation
  onConfirm: (data: IncidentLessonConfirmation) => Promise<IncidentLesson>
}

/** Collect only the reviewed lesson that may enter long-term incident memory. */
export function ConfirmedLessonForm({ investigation, onConfirm }: ConfirmedLessonFormProps) {
  const [service, setService] = useState('')
  const [environment, setEnvironment] = useState('production')
  const [rootCause, setRootCause] = useState('')
  const [resolution, setResolution] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [message, setMessage] = useState('')

  /** Send the explicitly reviewed root cause and resolution to the API. */
  async function submitLesson(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)
    setMessage('')
    try {
      const lesson = await onConfirm({
        investigation_id: investigation.id,
        service,
        environment,
        confirmed_root_cause: rootCause,
        validated_resolution: resolution,
        tenant_id: null,
      })
      setMessage(lesson.state === 'CONFIRMED'
        ? 'Confirmed lesson indexed for future investigations.'
        : `Lesson was not indexed: ${lesson.index_error ?? 'Unknown indexing error.'}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not confirm the lesson.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return <section className="confirmed-lesson-form" aria-label="Confirm incident lesson for memory">
    <div className="section-heading"><p>OPTIONAL · LEARN</p><h2>Confirm a reusable lesson</h2><span>Only a reviewed root cause and validated resolution are stored. Logs, hypotheses, and the full report are not saved to long-term memory.</span></div>
    <form onSubmit={(event) => void submitLesson(event)}>
      <label>Affected service<input minLength={1} onChange={(event) => setService(event.target.value)} placeholder="e.g. payment-api" required value={service} /></label>
      <label>Environment<input minLength={1} onChange={(event) => setEnvironment(event.target.value)} required value={environment} /></label>
      <label>Confirmed root cause<textarea minLength={1} onChange={(event) => setRootCause(event.target.value)} required rows={3} value={rootCause} /></label>
      <label>Validated resolution<textarea minLength={1} onChange={(event) => setResolution(event.target.value)} required rows={3} value={resolution} /></label>
      <button className="secondary-button" disabled={isSubmitting} type="submit">{isSubmitting ? 'Indexing confirmed lesson…' : 'Confirm lesson for memory'}</button>
      {message && <p className="form-status">{message}</p>}
    </form>
  </section>
}
