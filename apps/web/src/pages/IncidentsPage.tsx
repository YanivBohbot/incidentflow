import { useState } from 'react'
import type { Incident, Investigation } from '../api'
import { EmptyState } from '../components/ui/EmptyState'
import { IncidentForm } from '../features/incidents/IncidentForm'

type Severity = Incident['priority']
type SeverityFilter = 'ALL' | Severity

const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
const LIFECYCLE_LABELS: Record<string, string> = {
  PENDING: 'Pending',
  RUNNING: 'Running',
  AWAITING_HUMAN_REVIEW: 'Awaiting review',
  COMPLETED: 'Investigated',
  FAILED: 'Last run failed',
}

/** Most severe first, then most recent first. */
function bySeverityThenDate(left: Incident, right: Incident) {
  const severity = SEVERITY_ORDER.indexOf(left.priority) - SEVERITY_ORDER.indexOf(right.priority)
  return severity || Date.parse(right.created_at) - Date.parse(left.created_at)
}

type IncidentsPageProps = {
  incidents: Incident[]
  investigations: Investigation[]
  selectedIncident: Incident | null
  onCreateIncident: (data: Pick<Incident, 'title' | 'description' | 'priority'>) => Promise<void>
  onSelectIncident: (incident: Incident) => void
  onStartInvestigation: () => Promise<void>
  isCreateFormOpen: boolean
  onCloseCreateForm: () => void
}

/**
 * Two columns at the same height: the incident queue (step 1) on the left, and on the right
 * either the report form or the selected incident with its launch button (step 2).
 */
export function IncidentsPage({ incidents, investigations, selectedIncident, onCreateIncident, onSelectIncident, onStartInvestigation, isCreateFormOpen, onCloseCreateForm }: IncidentsPageProps) {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('ALL')

  async function createAndSelect(data: Pick<Incident, 'title' | 'description' | 'priority'>) {
    await onCreateIncident(data)
    onCloseCreateForm()
  }

  /** Investigations are listed newest first, so the first match is the latest run. */
  const latestInvestigation = (incident: Incident) => investigations.find((item) => item.incident_id === incident.id)
  const countFor = (severity: SeverityFilter) => severity === 'ALL' ? incidents.length : incidents.filter((incident) => incident.priority === severity).length
  const visibleIncidents = incidents
    .filter((incident) => severityFilter === 'ALL' || incident.priority === severityFilter)
    .sort(bySeverityThenDate)

  return (
    <div className="page-grid incidents-layout">
      <section className="surface incident-list-surface">
        <div className="section-heading">
          <p>STEP 1 · CHOOSE AN INCIDENT</p>
          <h2>Incident queue</h2>
          <span>Sorted by severity. Filter by severity, then select an incident to investigate it.</span>
        </div>
        <div aria-label="Filter by severity" className="severity-filter" role="group">
          {(['ALL', ...SEVERITY_ORDER] as SeverityFilter[]).map((severity) => (
            <button aria-pressed={severityFilter === severity} className={`severity-chip severity-chip-${severity.toLowerCase()} ${severityFilter === severity ? 'is-active' : ''}`} key={severity} onClick={() => setSeverityFilter(severity)} type="button">
              {severity === 'ALL' ? 'All' : severity.charAt(0) + severity.slice(1).toLowerCase()}
              <b>{countFor(severity)}</b>
            </button>
          ))}
        </div>
        {incidents.length === 0 ? (
          <EmptyState description="Report the operational problem first. You can launch the multi-agent investigation afterwards." title="No incidents reported yet" />
        ) : visibleIncidents.length === 0 ? (
          <EmptyState description="No incident has this severity. Choose another filter." title="Nothing here" />
        ) : (
          <ul className="incident-list">
            {visibleIncidents.map((incident) => {
              const latest = latestInvestigation(incident)
              return (
                <li className={selectedIncident?.id === incident.id ? 'is-selected' : ''} key={incident.id}>
                  <button onClick={() => { onCloseCreateForm(); onSelectIncident(incident) }} type="button">
                    <span className="incident-badges">
                      <span className={`priority priority-${incident.priority.toLowerCase()}`}>{incident.priority}</span>
                      <span className={`investigation-state ${latest ? `lifecycle-${latest.lifecycle.toLowerCase()}` : 'is-new'}`}>
                        {latest ? LIFECYCLE_LABELS[latest.lifecycle] ?? latest.lifecycle : 'Not investigated'}
                      </span>
                    </span>
                    <strong>{incident.title}</strong>
                    <small>{new Date(incident.created_at).toLocaleString()}</small>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="surface incident-detail-surface">
        {isCreateFormOpen ? (
          <>
            <div className="section-heading">
              <p>REPORT AN INCIDENT</p>
              <h2>Describe the operational problem</h2>
              <span>This only records the incident in the queue. No agent and no Jira call runs yet.</span>
            </div>
            <IncidentForm onSubmit={createAndSelect} />
            <button className="quiet-button form-cancel" onClick={onCloseCreateForm} type="button">Close form</button>
          </>
        ) : selectedIncident ? (
          <div className="selected-incident">
            <p>STEP 2 · INVESTIGATE</p>
            <span className={`priority priority-${selectedIncident.priority.toLowerCase()}`}>{selectedIncident.priority}</span>
            <h3>{selectedIncident.title}</h3>
            <span>{selectedIncident.description}</span>
            <small className="selected-incident-hint">
              This description is sent to the Investigation Supervisor, which chooses the specialist agents.
              Ask for a Jira write explicitly (for example “create a Jira issue in project SAM1”) and it will pause for your approval.
            </small>
            <button className="primary-button" onClick={() => void onStartInvestigation()} type="button">Launch multi-agent investigation</button>
          </div>
        ) : (
          <EmptyState description="Select an incident in the queue to see its details and launch the investigation." title="STEP 2 · Select an incident" />
        )}
      </section>
    </div>
  )
}
