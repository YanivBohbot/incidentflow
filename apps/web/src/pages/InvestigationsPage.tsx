import type { Incident, IncidentLesson, IncidentLessonConfirmation, Investigation } from '../api'
import { EmptyState } from '../components/ui/EmptyState'
import { AgentTrace } from '../features/investigations/AgentTrace'
import { ConfirmedLessonForm } from '../features/investigations/ConfirmedLessonForm'
import { ReportDetails } from '../features/investigations/ReportDetails'

type InvestigationsPageProps = {
  incidents: Incident[]
  investigations: Investigation[]
  selectedInvestigation: Investigation | null
  onSelectInvestigation: (investigation: Investigation) => void
  onConfirmLesson: (data: IncidentLessonConfirmation) => Promise<IncidentLesson>
}

/** Show past investigations and let an operator curate completed lessons. */
export function InvestigationsPage({ incidents, investigations, selectedInvestigation, onSelectInvestigation, onConfirmLesson }: InvestigationsPageProps) {
  /** Find the incident that gives each investigation its operator-facing title. */
  const incidentFor = (investigation: Investigation) => incidents.find((incident) => incident.id === investigation.incident_id)
  /** Convert persisted lifecycle values into readable labels. */
  const statusLabel = (lifecycle: string) => lifecycle.charAt(0) + lifecycle.slice(1).toLowerCase()

  return <div className="page-grid investigations-layout"><aside className="surface investigation-list-surface"><div className="section-heading"><p>STEP 2 · ANALYSE</p><h2>Recent investigations</h2><span>Each investigation belongs to one incident. Select it to view the report or understand a failure.</span></div>{investigations.length === 0 ? <EmptyState description="Select an incident and launch the multi-agent investigation when you are ready." title="No investigations yet" /> : <ul className="investigation-list">{investigations.map((investigation) => { const incident = incidentFor(investigation); return <li key={investigation.id}><button aria-pressed={selectedInvestigation?.id === investigation.id} className={selectedInvestigation?.id === investigation.id ? 'is-selected' : ''} onClick={() => onSelectInvestigation(investigation)} type="button"><span className={`lifecycle lifecycle-${investigation.lifecycle.toLowerCase()}`}>{statusLabel(investigation.lifecycle)}</span><strong>{incident?.title ?? 'Source incident unavailable'}</strong><small>{investigation.report?.summary ?? investigation.error_message ?? 'No report returned.'}</small><small>Started {new Date(investigation.created_at).toLocaleString()}</small></button></li> })}</ul>}</aside><section className="surface report-surface">{selectedInvestigation ? <>{selectedInvestigation.report ? <ReportDetails report={selectedInvestigation.report} /> : <div className="investigation-status"><p>INVESTIGATION STATUS</p><h2 className={`status-${selectedInvestigation.lifecycle.toLowerCase()}`}>{statusLabel(selectedInvestigation.lifecycle)}</h2><strong>Incident: {incidentFor(selectedInvestigation)?.title ?? 'Source incident unavailable'}</strong><p>{selectedInvestigation.error_message ?? (selectedInvestigation.lifecycle === 'RUNNING' ? 'The agents are working. Follow each delegation live below.' : selectedInvestigation.lifecycle === 'AWAITING_HUMAN_REVIEW' ? 'The workflow is paused until an operator decides on the Approvals page.' : 'The investigation did not return a report.')}</p>{selectedInvestigation.lifecycle === 'FAILED' && <span>This record is historical. You can return to Incidents, select the source incident, then launch a new investigation after checking the context.</span>}</div>}<AgentTrace investigation={selectedInvestigation} />{selectedInvestigation.lifecycle === 'COMPLETED' && <ConfirmedLessonForm investigation={selectedInvestigation} onConfirm={onConfirmLesson} />}</> : <EmptyState description="Choose an investigation to inspect its sources, hypotheses, next actions, or failure details." title="Select an investigation" />}</section></div>
}
