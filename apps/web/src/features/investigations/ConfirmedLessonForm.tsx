/** Save a confirmed root cause and fix as a lesson for future investigations. */
import { useState } from 'react'
import type { Incident, IncidentLesson, IncidentLessonConfirmation, Investigation } from '../../api'

type ConfirmedLessonFormProps = {
  investigation: Investigation
  /** Source incident, used to prefill the affected service. */
  incident?: Incident
  onConfirm: (data: IncidentLessonConfirmation) => Promise<IncidentLesson>
  /** Called once the lesson is indexed, so the parent can close the form. */
  onSaved?: () => void
}

/** Collect only the reviewed lesson that may enter long-term incident memory. */
export function ConfirmedLessonForm({ investigation, incident, onConfirm, onSaved }: ConfirmedLessonFormProps) {
  const suggestedResolution = investigation.report?.proposed_actions?.[0]
  const [service, setService] = useState(incident?.service ?? '')
  const [environment, setEnvironment] = useState('production')
  const [rootCause, setRootCause] = useState(investigation.report?.root_cause ?? '')
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
      if (lesson.state === 'CONFIRMED') {
        setMessage('Confirmed lesson indexed for future investigations.')
        onSaved?.()
      } else {
        setMessage(`Lesson was not indexed: ${lesson.index_error ?? 'Unknown indexing error.'}`)
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not confirm the lesson.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return <section className="confirmed-lesson-form" aria-label="Confirm incident lesson for memory">
    <div className="section-heading"><p>OPTIONAL · LEARN</p><h2>Confirm a reusable lesson</h2><span>Once the problem is really fixed, store what caused it and what fixed it, so future investigations of a similar incident can reuse it. The service and root cause are prefilled from the report: correct them if the real cause was different. Logs, hypotheses, and the full report are not saved.</span></div>
    <form onSubmit={(event) => void submitLesson(event)}>
      <label>Affected service<input minLength={1} onChange={(event) => setService(event.target.value)} placeholder="e.g. payment-api" required value={service} /></label>
      <label>Environment<input minLength={1} onChange={(event) => setEnvironment(event.target.value)} required value={environment} /></label>
      <label>Confirmed root cause<textarea minLength={1} onChange={(event) => setRootCause(event.target.value)} required rows={3} value={rootCause} /></label>
      <label>Validated resolution<textarea minLength={1} onChange={(event) => setResolution(event.target.value)} placeholder={suggestedResolution ? `What actually fixed it, e.g. ${suggestedResolution}` : 'What actually fixed it'} required rows={3} value={resolution} /></label>
      <button className="secondary-button" disabled={isSubmitting} type="submit">{isSubmitting ? 'Indexing confirmed lesson…' : 'Confirm lesson for memory'}</button>
      {message && <p className="form-status">{message}</p>}
    </form>
  </section>
}
