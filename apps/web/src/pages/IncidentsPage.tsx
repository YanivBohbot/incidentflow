import type { Incident } from '../api'
import { EmptyState } from '../components/ui/EmptyState'
import { IncidentForm } from '../features/incidents/IncidentForm'

type IncidentsPageProps = {
  incidents: Incident[]
  selectedIncident: Incident | null
  onCreateIncident: (data: Pick<Incident, 'title' | 'description' | 'priority'>) => Promise<void>
  onSelectIncident: (incident: Incident) => void
  onStartInvestigation: () => Promise<void>
  isCreateFormOpen: boolean
  onCloseCreateForm: () => void
}

export function IncidentsPage({ incidents, selectedIncident, onCreateIncident, onSelectIncident, onStartInvestigation, isCreateFormOpen, onCloseCreateForm }: IncidentsPageProps) {
  async function createAndSelect(data: Pick<Incident, 'title' | 'description' | 'priority'>) {
    await onCreateIncident(data)
    onCloseCreateForm()
  }

  return <div className={`page-grid incidents-layout ${isCreateFormOpen ? '' : 'incidents-list-focused'}`}><section className="surface incident-list-surface"><div className="section-heading"><p>STEP 1 · REPORT</p><h2>Incident queue</h2><span>An incident is a record of a real operational problem. Use “Report incident” above to add one, then select it and launch an investigation when it is ready.</span></div>{incidents.length === 0 ? <EmptyState description="Report the operational problem first. You can launch the multi-agent investigation afterwards." title="No incidents reported yet" /> : <ul className="incident-list">{incidents.map((incident) => <li className={selectedIncident?.id === incident.id ? 'is-selected' : ''} key={incident.id}><button onClick={() => onSelectIncident(incident)} type="button"><span className={`priority priority-${incident.priority.toLowerCase()}`}>{incident.priority}</span><strong>{incident.title}</strong><small>{incident.status} · {new Date(incident.created_at).toLocaleString()}</small></button></li>)}</ul>}{selectedIncident && <div className="selected-incident"><p>STEP 2 · INVESTIGATE</p><h3>{selectedIncident.title}</h3><span>{selectedIncident.description}</span><button className="primary-button" onClick={() => void onStartInvestigation()} type="button">Launch multi-agent investigation</button></div>}</section>{isCreateFormOpen && <section className="surface form-surface"><div className="section-heading"><p>REPORT AN INCIDENT</p><h2>Describe the operational problem</h2><span>This does not call Jira or the agents. It only creates an incident record that you can investigate next.</span></div><IncidentForm onSubmit={createAndSelect} /><button className="quiet-button form-cancel" onClick={onCloseCreateForm} type="button">Close form</button></section>}</div>
}
