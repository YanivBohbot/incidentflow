import { useEffect, useMemo, useRef, useState } from 'react'
import type { Incident, Investigation } from '../api'
import { EmptyState } from '../components/ui/EmptyState'
import { activeIncidents } from '../features/incidents/activeIncidents'
import { IncidentForm } from '../features/incidents/IncidentForm'

type Severity = Incident['priority']
type SeverityFilter = 'ALL' | Severity

const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
const LIFECYCLE_LABELS: Record<string, string> = {
  PENDING: 'Queued',
  RUNNING: 'Running',
  AWAITING_HUMAN_REVIEW: 'Awaiting review',
  COMPLETED: 'Investigated',
  FAILED: 'Last run failed',
}

const NEW_HIGHLIGHT_MS = 4_000
const DEMO_COOLDOWN_MS = 10_000
const SOURCE_LABELS: Record<Incident['source'], string> = { MANUAL: 'Manual', CLOUDWATCH_ALARM: 'CloudWatch alarm' }

/** "12 s ago", "5 min ago", "3 h ago", "2 d ago". */
function relativeTime(iso: string, now: number) {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (seconds < 60) return `${seconds} s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86_400)} d ago`
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
  /** True while the start request is in flight, so a double click cannot queue twice. */
  isStartingInvestigation?: boolean
  onCloseCreateForm: () => void
  demoEnabled?: boolean
  isDemoStarting?: boolean
  onRunDemo?: () => Promise<void>
  /** Called once per page visit when the demo is enabled. */
  onAutoStartDemo?: () => Promise<void>
}

/**
 * Two columns at the same height: the incident queue (step 1) on the left, and on the right
 * either the report form or the selected incident with its launch button (step 2).
 */
export function IncidentsPage({ incidents: allIncidents, investigations, selectedIncident, onCreateIncident, onSelectIncident, onStartInvestigation, isCreateFormOpen, isStartingInvestigation = false, onCloseCreateForm, demoEnabled = false, isDemoStarting = false, onRunDemo, onAutoStartDemo }: IncidentsPageProps) {
  const incidents = useMemo(() => activeIncidents(allIncidents), [allIncidents])
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('ALL')
  const [now, setNow] = useState(() => Date.now())
  const [newIds, setNewIds] = useState<Set<string>>(new Set())
  const [demoCooldown, setDemoCooldown] = useState(false)
  const previousIds = useRef<Set<string> | null>(null)
  const timers = useRef<number[]>([])
  const autoStarted = useRef(false)

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1_000)
    const pending = timers.current
    return () => { window.clearInterval(tick); pending.forEach((timer) => window.clearTimeout(timer)) }
  }, [])

  // The page is mounted once per visit, so the ref gives "once per visit" across re-renders.
  useEffect(() => {
    if (!demoEnabled || autoStarted.current) return
    autoStarted.current = true
    void onAutoStartDemo?.()
  }, [demoEnabled, onAutoStartDemo])

  // Mark incidents missing from the previous list (never on the first render) for 4 s.
  useEffect(() => {
    const ids = new Set(incidents.map((item) => item.id))
    const previous = previousIds.current
    previousIds.current = ids
    if (!previous) return
    const added = [...ids].filter((id) => !previous.has(id))
    if (added.length === 0) return
    setNewIds((current) => new Set([...current, ...added]))
    timers.current.push(window.setTimeout(() => {
      setNewIds((current) => new Set([...current].filter((id) => !added.includes(id))))
    }, NEW_HIGHLIGHT_MS))
  }, [incidents])

  async function runDemo() {
    setDemoCooldown(true)
    timers.current.push(window.setTimeout(() => setDemoCooldown(false), DEMO_COOLDOWN_MS))
    await onRunDemo?.()
  }

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
          {demoEnabled && (
            <button className="quiet-button run-demo-button" disabled={demoCooldown || isDemoStarting} onClick={() => void runDemo()} type="button">
              {demoCooldown || isDemoStarting ? 'Demo running…' : 'Run demo'}
            </button>
          )}
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
                <li className={`${selectedIncident?.id === incident.id ? 'is-selected' : ''} ${newIds.has(incident.id) ? 'is-new' : ''}`.trim()} key={incident.id}>
                  <button onClick={() => { onCloseCreateForm(); onSelectIncident(incident) }} type="button">
                    <span className="incident-badges">
                      <span className={`priority priority-${incident.priority.toLowerCase()}`}>{incident.priority}</span>
                      <span className={`investigation-state ${latest ? `lifecycle-${latest.lifecycle.toLowerCase()}` : 'is-new'}`}>
                        {latest ? LIFECYCLE_LABELS[latest.lifecycle] ?? latest.lifecycle : 'Not investigated'}
                      </span>
                      <span className={`source-badge source-${(incident.source ?? 'MANUAL').toLowerCase()}`}>{SOURCE_LABELS[incident.source] ?? 'Manual'}</span>
                    </span>
                    <strong>{incident.title}</strong>
                    <small title={new Date(incident.created_at).toLocaleString()}>
                      {incident.service ? `${incident.service} · ` : ''}{relativeTime(incident.created_at, now)}
                    </small>
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
            <button className="primary-button" disabled={isStartingInvestigation} onClick={() => void onStartInvestigation()} type="button">
              {isStartingInvestigation ? 'Queueing the investigation…' : 'Launch multi-agent investigation'}
            </button>
          </div>
        ) : (
          <EmptyState description="Select an incident in the queue to see its details and launch the investigation." title="STEP 2 · Select an incident" />
        )}
      </section>
    </div>
  )
}
