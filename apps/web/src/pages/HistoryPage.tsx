/** History page: events grouped by incident category on the left, one incident's journal on the right. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { Incident, IncidentEvent, IncidentEventKind, Investigation } from '../api'
import { EmptyState } from '../components/ui/EmptyState'

export const DECISION_KINDS: IncidentEventKind[] = ['REVIEW_DECIDED', 'INCIDENT_RESOLVED', 'LESSON_SAVED']

const REFRESH_MS = 10_000
const VISIBLE_CHIPS = 6
const DEMO_RUNS = 'Demo runs'

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

/** The type of incident: its service, or its title when it has none. */
const incidentCategory = (incident: Pick<Incident, 'service' | 'title'>) => incident.service || incident.title
const eventCategory = (event: IncidentEvent) => event.incident_service || event.incident_title || DEMO_RUNS

type HistoryPageProps = {
  incidents: Incident[]
  /** Used to tell incidents never investigated, which are hidden by default once closed. */
  investigations: Investigation[]
  /** Incident to open, asked by a "View journal" link; a new focusRequest re-applies it. */
  focusIncidentId?: string
  focusRequest?: number
  /** False while another tab is shown: the page keeps its state but stops polling. */
  active?: boolean
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

export function HistoryPage({ incidents, investigations, focusIncidentId, focusRequest, active = true, onOpenInvestigation }: HistoryPageProps) {
  const [events, setEvents] = useState<IncidentEvent[]>([])
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [decisionsOnly, setDecisionsOnly] = useState(false)
  const [showAllChips, setShowAllChips] = useState(false)
  const [showUntouched, setShowUntouched] = useState(false)
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | undefined>(focusIncidentId)
  const [journal, setJournal] = useState<IncidentEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  /** True once "Load more" has added older pages, so a refresh must not drop them. */
  const paged = useRef(false)

  const kinds = decisionsOnly ? DECISION_KINDS : undefined

  /** Categories with their incident count, most incidents first. */
  const chips = useMemo(() => {
    const investigated = new Set(investigations.map((item) => item.incident_id))
    const counted = showUntouched ? incidents : incidents.filter((item) => item.status !== 'CLOSED' || investigated.has(item.id))
    const counts = new Map<string, number>()
    for (const item of counted) counts.set(incidentCategory(item), (counts.get(incidentCategory(item)) ?? 0) + 1)
    return [...counts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
  }, [incidents, investigations, showUntouched])
  const shownChips = showAllChips ? chips : chips.slice(0, VISIBLE_CHIPS)

  /** Loaded events by category, then one card per incident read in time order. */
  const groups = useMemo(() => {
    const byName = new Map<string, Map<string, IncidentEvent[]>>()
    for (const item of events) {
      const cards = byName.get(eventCategory(item)) ?? new Map<string, IncidentEvent[]>()
      const key = item.incident_id ?? DEMO_RUNS
      cards.set(key, [...(cards.get(key) ?? []), item])
      byName.set(eventCategory(item), cards)
    }
    const chronological = (left: IncidentEvent, right: IncidentEvent) =>
      left.occurred_at.localeCompare(right.occurred_at) || left.id.localeCompare(right.id)
    return [...byName.entries()].map(([name, cards]) => ({
      name,
      latest: [...cards.values()][0][0],
      cards: [...cards.entries()].map(([key, items]) => ({
        key,
        incidentId: key === DEMO_RUNS ? undefined : key,
        title: items[0].incident_title ?? DEMO_RUNS,
        items: [...items].sort(chronological),
      })),
    }))
  }, [events])

  /** Fetch the first page: a reset replaces the list, a refresh only adds new events on top. */
  const loadFirstPage = useCallback(async (mode: 'reset' | 'refresh') => {
    try {
      const page = await api.getHistory({ category, kinds, hideUntouched: !showUntouched, before: undefined })
      if (mode === 'reset' || !paged.current) {
        paged.current = false
        setEvents(page.events)
        setNextBefore(page.next_before)
      } else {
        setEvents((current) => {
          const known = new Set(current.map((item) => item.id))
          return [...page.events.filter((item) => !known.has(item.id)), ...current]
        })
      }
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the history.')
    }
  }, [category, kinds, showUntouched])

  useEffect(() => { void loadFirstPage('reset') }, [loadFirstPage])

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void loadFirstPage('refresh')
    }, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [active, loadFirstPage])

  useEffect(() => {
    if (focusRequest && focusIncidentId) setSelectedIncidentId(focusIncidentId)
  }, [focusIncidentId, focusRequest])

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
    const page = await api.getHistory({ category, kinds, hideUntouched: !showUntouched, before: nextBefore })
    paged.current = true
    setEvents((current) => [...current, ...page.events])
    setNextBefore(page.next_before)
  }

  const isOpen = (name: string, index: number) => toggled[name] ?? (category ? name === category : index === 0)

  const selectedTitle = incidents.find((item) => item.id === selectedIncidentId)?.title
    ?? journal[0]?.incident_title ?? 'Incident'

  return (
    <div className="page-grid history-layout">
      <section className="surface history-surface">
        <div className="section-heading">
          <p>DECISION TIMELINE</p>
          <h2>What happened, by type of incident</h2>
          <span>Incidents of the same service are grouped. Open a group, then select an event to read its incident journal.</span>
        </div>
        <div aria-label="Filter history" className="history-filters" role="group">
          <button aria-pressed={!category} className={`severity-chip ${!category ? 'is-active' : ''}`} onClick={() => setCategory(undefined)} type="button">All</button>
          {shownChips.map(([name, count]) => (
            <button aria-label={`${name} ${count}`} aria-pressed={category === name} className={`severity-chip ${category === name ? 'is-active' : ''}`} key={name} onClick={() => setCategory(category === name ? undefined : name)} title={name} type="button">
              <span className="chip-label">{name}</span> <b>{count}</b>
            </button>
          ))}
          {chips.length > VISIBLE_CHIPS && (
            <button className="severity-chip" onClick={() => setShowAllChips((value) => !value)} type="button">
              {showAllChips ? 'Less' : `+${chips.length - VISIBLE_CHIPS}`}
            </button>
          )}
          <span className="history-filter-gap" />
          <button aria-pressed={showUntouched} className={`severity-chip ${showUntouched ? 'is-active' : ''}`} onClick={() => setShowUntouched((value) => !value)} title="Incidents closed without ever being investigated, mostly old demo runs" type="button">Show untouched</button>
          <button aria-pressed={decisionsOnly} className={`severity-chip ${decisionsOnly ? 'is-active' : ''}`} onClick={() => setDecisionsOnly((value) => !value)} type="button">Decisions</button>
        </div>
        {error && <p className="proposal-error" role="alert">{error}</p>}
        {groups.length === 0 && !error ? <EmptyState description="Events appear here as incidents are raised, investigated, and resolved." title="Nothing recorded yet" /> : (
          <div className="history-groups">
            {groups.map((item, index) => {
              const open = isOpen(item.name, index)
              return (
                <section aria-label={item.name} className={`history-group ${open ? 'is-open' : ''}`} key={item.name}>
                  <button aria-expanded={open} className="history-group-heading" onClick={() => setToggled((current) => ({ ...current, [item.name]: !open }))} type="button">
                    <span aria-hidden="true">{open ? '▾' : '▸'}</span>
                    <strong>{item.name}</strong>
                    <small>{item.cards.length} {item.cards.length > 1 ? 'entries' : 'entry'} · latest <EventTime event={item.latest} /></small>
                  </button>
                  {open && item.cards.map((card) => (
                    <article aria-label={card.title} className={`history-card ${card.incidentId && card.incidentId === selectedIncidentId ? 'is-selected' : ''}`} key={card.key}>
                      <h3>
                        {card.incidentId
                          ? <button className="history-card-title" onClick={() => setSelectedIncidentId(card.incidentId)} type="button">{card.title}</button>
                          : card.title}
                      </h3>
                      <ol className="history-list">
                        {card.items.map((entry) => (
                          <li key={entry.id}>
                            <button disabled={!entry.incident_id} onClick={() => entry.incident_id && setSelectedIncidentId(entry.incident_id)} type="button">
                              <span aria-hidden="true" className="history-icon">{KIND_ICONS[entry.kind]}</span>
                              <span className="history-body">
                                <strong>{entry.summary}</strong>
                                <small><EventTime event={entry} /> · {entry.actor}</small>
                                <EventFacts event={entry} />
                              </span>
                            </button>
                          </li>
                        ))}
                      </ol>
                    </article>
                  ))}
                </section>
              )
            })}
          </div>
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
        </> : <EmptyState description="Open a group on the left and select an event to read the full journal of its incident." title="Select an incident" />}
      </section>
    </div>
  )
}
