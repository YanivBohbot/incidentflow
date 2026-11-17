/** History page: the decision timeline on the left, the selected incident's journal on the right. */
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { Incident, IncidentEvent, IncidentEventKind } from '../api'
import { EmptyState } from '../components/ui/EmptyState'

export const DECISION_KINDS: IncidentEventKind[] = ['REVIEW_DECIDED', 'INCIDENT_RESOLVED', 'LESSON_SAVED']

const REFRESH_MS = 10_000

const KIND_ICONS: Record<IncidentEventKind, string> = {
  INCIDENT_CREATED: '🚨',
  INVESTIGATION_STARTED: '🔎',
  REVIEW_REQUESTED: '⏸',
  REVIEW_DECIDED: '✋',
  INVESTIGATION_COMPLETED: '📋',
  INVESTIGATION_FAILED: '⛔',
  INCIDENT_RESOLVED: '✅',
  INCIDENT_CLOSED: '📦',
  LESSON_SAVED: '🧠',
  DEMO_RUN_STARTED: '▶',
}

type HistoryPageProps = {
  incidents: Incident[]
  /** Incident whose journal opens first, e.g. from a "View journal" link. */
  initialIncidentId?: string
  onOpenInvestigation: (investigationId: string) => void
}

/** "≈ 17 Nov, 12:00" for reconstructed events whose time is approximate. */
function EventTime({ event }: { event: IncidentEvent }) {
  const time = new Date(event.occurred_at).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  return <time dateTime={event.occurred_at} title={event.reconstructed ? 'Reconstructed: approximate time' : undefined}>{event.reconstructed ? `≈ ${time}` : time}</time>
}

/** Extra facts worth a glance: the Jira key, the confidence, the decision reason. */
function EventFacts({ event }: { event: IncidentEvent }) {
  const facts = [
    typeof event.details.jira_key === 'string' ? event.details.jira_key : null,
    typeof event.details.confidence === 'number' ? `${Math.round(event.details.confidence * 100)}%` : null,
    typeof event.details.reason === 'string' && event.details.reason ? `“${event.details.reason}”` : null,
  ].filter(Boolean)
  return facts.length ? <small className="history-facts">{facts.join(' · ')}</small> : null
}

export function HistoryPage({ incidents, initialIncidentId, onOpenInvestigation }: HistoryPageProps) {
  const [events, setEvents] = useState<IncidentEvent[]>([])
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [incidentFilter, setIncidentFilter] = useState<string | undefined>(undefined)
  const [decisionsOnly, setDecisionsOnly] = useState(false)
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | undefined>(initialIncidentId)
  const [journal, setJournal] = useState<IncidentEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  const kinds = decisionsOnly ? DECISION_KINDS : undefined

  /** Reload the first page for the current filters. */
  const loadFirstPage = useCallback(async () => {
    try {
      const page = await api.getHistory({ incidentId: incidentFilter, kinds, before: undefined })
      setEvents(page.events)
      setNextBefore(page.next_before)
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the history.')
    }
  }, [incidentFilter, kinds])

  useEffect(() => {
    void loadFirstPage()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void loadFirstPage()
    }, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [loadFirstPage])

  useEffect(() => {
    if (!selectedIncidentId) return
    let isCurrent = true
    api.getIncidentEvents(selectedIncidentId)
      .then((items) => { if (isCurrent) setJournal(items) })
      .catch(() => { if (isCurrent) setJournal([]) })
    return () => { isCurrent = false }
  }, [selectedIncidentId, events])

  async function loadMore() {
    if (!nextBefore) return
    const page = await api.getHistory({ incidentId: incidentFilter, kinds, before: nextBefore })
    setEvents((current) => [...current, ...page.events])
    setNextBefore(page.next_before)
  }

  const selectedTitle = incidents.find((item) => item.id === selectedIncidentId)?.title
    ?? journal[0]?.incident_title ?? 'Incident'

  return (
    <div className="page-grid history-layout">
      <section className="surface history-surface">
        <div className="section-heading">
          <p>DECISION TIMELINE</p>
          <h2>What happened, newest first</h2>
          <span>Every alarm, investigation, operator decision, resolution, and lesson. Select one to open its incident journal.</span>
        </div>
        <div className="history-filters">
          <select aria-label="Filter by incident" onChange={(change) => setIncidentFilter(change.target.value || undefined)} value={incidentFilter ?? ''}>
            <option value="">All incidents</option>
            {incidents.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
          <button aria-pressed={decisionsOnly} className={`severity-chip ${decisionsOnly ? 'is-active' : ''}`} onClick={() => setDecisionsOnly((value) => !value)} type="button">Decisions only</button>
        </div>
        {error && <p className="proposal-error" role="alert">{error}</p>}
        {events.length === 0 && !error ? <EmptyState description="Events appear here as incidents are raised, investigated, and resolved." title="Nothing recorded yet" /> : (
          <ol aria-label="Chronology" className="history-list">
            {events.map((item) => (
              <li className={item.incident_id === selectedIncidentId ? 'is-selected' : ''} key={item.id}>
                <button disabled={!item.incident_id} onClick={() => item.incident_id && setSelectedIncidentId(item.incident_id)} type="button">
                  <span aria-hidden="true" className="history-icon">{KIND_ICONS[item.kind]}</span>
                  <span className="history-body">
                    <strong>{item.summary}</strong>
                    <small><EventTime event={item} /> · {item.incident_title ?? 'Demo'} · {item.actor}</small>
                    <EventFacts event={item} />
                  </span>
                </button>
              </li>
            ))}
          </ol>
        )}
        {nextBefore && <button className="quiet-button" onClick={() => void loadMore()} type="button">Load more</button>}
      </section>

      <section className="surface history-surface">
        {selectedIncidentId ? <>
          <div className="section-heading">
            <p>INCIDENT JOURNAL</p>
            <h2>{selectedTitle}</h2>
            <span>Everything that happened to this incident, in order. “≈” marks a reconstructed, approximate time.</span>
          </div>
          <ol aria-label="Journal" className="journal-list">
            {journal.map((item) => (
              <li className={`journal-step journal-${item.kind.toLowerCase()}`} key={item.id}>
                <span aria-hidden="true" className="history-icon">{KIND_ICONS[item.kind]}</span>
                <div className="history-body">
                  <strong>{item.summary}</strong>
                  <small><EventTime event={item} /> · {item.actor}</small>
                  <EventFacts event={item} />
                  {item.investigation_id && <button className="quiet-button" onClick={() => onOpenInvestigation(item.investigation_id as string)} type="button">Open investigation</button>}
                </div>
              </li>
            ))}
          </ol>
        </> : <EmptyState description="Select an event on the left to read the full journal of its incident." title="Select an incident" />}
      </section>
    </div>
  )
}
