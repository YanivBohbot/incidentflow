/** Dashboard state and actions, kept in sync with the API by polling. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import { activeIncidents, resolvedIncidents } from '../features/incidents/activeIncidents'
import type {
  HumanReviewDecision,
  Incident,
  IncidentLessonConfirmation,
  Investigation,
  OperationalMetrics,
  Readiness,
} from '../api'

const WORKSPACE_REFRESH_MS = 10_000
const INCIDENTS_PAGE_REFRESH_MS = 3_000
const ACTIVE_INVESTIGATION_REFRESH_MS = 1_500

const LIFECYCLE_MESSAGES: Record<string, string> = {
  RUNNING: 'Investigation running…',
  COMPLETED: 'Investigation completed.',
  AWAITING_HUMAN_REVIEW: 'Investigation paused for a human decision.',
  FAILED: 'Investigation finished with a failure.',
}

const isNewer = (candidate: Investigation, current: Investigation) =>
  Date.parse(candidate.updated_at) > Date.parse(current.updated_at)

/** Merge a fetched list into the current one; a row is replaced only by a newer snapshot. */
function mergeInvestigations(current: Investigation[], incoming: Investigation[], local: Investigation[]) {
  const byId = new Map(current.map((item) => [item.id, item]))
  const merged = incoming.map((item) => {
    const existing = byId.get(item.id)
    return existing && !isNewer(item, existing) ? existing : item
  })
  const known = new Set(merged.map((item) => item.id))
  return [...local.filter((item) => !known.has(item.id)), ...merged]
}

/** Workspace state: polls incidents and investigations (faster on Incidents and during a run). */
export function useIncidentFlow(activePage: string = 'overview') {
  const refreshMs = activePage === 'incidents' ? INCIDENTS_PAGE_REFRESH_MS : WORKSPACE_REFRESH_MS
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [investigations, setInvestigations] = useState<Investigation[]>([])
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [selectedInvestigation, setSelectedInvestigation] = useState<Investigation | null>(null)
  const [operationalMetrics, setOperationalMetrics] = useState<OperationalMetrics>({
    investigations_by_lifecycle: {},
    requests_by_status: {},
  })
  const [readiness, setReadiness] = useState<Readiness>({ status: 'starting' })
  const [statusMessage, setStatusMessage] = useState('Connecting to the IncidentFlow API…')
  const [isLoading, setIsLoading] = useState(true)
  const [demoEnabled, setDemoEnabled] = useState(false)
  const [isDemoStarting, setIsDemoStarting] = useState(false)
  const startInFlight = useRef(false)
  const [isStartingInvestigation, setIsStartingInvestigation] = useState(false)

  const localRows = useRef(new Map<string, Investigation>())
  const applyList = useCallback((items: Investigation[]) => {
    const local = [...localRows.current.values()]
    for (const item of items) localRows.current.delete(item.id)
    setInvestigations((current) => mergeInvestigations(current, items, local))
  }, [])

  const refreshInvestigations = useCallback(async () => {
    const items = await api.listInvestigations()
    applyList(items)
    return items
  }, [applyList])

  const refreshWorkspace = useCallback(async () => {
    const [incidentItems, investigationItems, readinessSnapshot, metricsSnapshot] = await Promise.all([
      api.listIncidents(),
      api.listInvestigations(),
      api.getReadiness(),
      api.getOperationalMetrics(),
    ])
    setIncidents(incidentItems)
    applyList(investigationItems)
    setReadiness(readinessSnapshot)
    setOperationalMetrics(metricsSnapshot)
    return { incidentItems, investigationItems }
  }, [applyList])

  useEffect(() => {
    let isCurrent = true
    async function loadWorkspace() {
      try {
        await refreshWorkspace()
        if (!isCurrent) return
        setStatusMessage('API connected')
      } catch (error) {
        if (isCurrent) setStatusMessage(error instanceof Error ? error.message : 'Could not connect to the API.')
      } finally {
        if (isCurrent) setIsLoading(false)
      }
    }
    void loadWorkspace()
    return () => { isCurrent = false }
  }, [refreshWorkspace])

  useEffect(() => {
    let isCurrent = true
    api.getDemoStatus()
      .then((status) => { if (isCurrent) setDemoEnabled(status.enabled) })
      .catch(() => undefined)
    return () => { isCurrent = false }
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refreshWorkspace().catch(() => undefined)
    }, refreshMs)
    const refreshOnFocus = () => {
      if (document.visibilityState === 'visible') void refreshWorkspace().catch(() => undefined)
    }
    document.addEventListener('visibilitychange', refreshOnFocus)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refreshOnFocus)
    }
  }, [refreshWorkspace, refreshMs])

  /** Manual demo run; a failure (including 403 for a viewer) goes to the status message. */
  const startDemoRun = useCallback(async () => {
    setIsDemoStarting(true)
    setStatusMessage('Starting the demo…')
    try {
      await api.startDemoRun(false)
      setStatusMessage('Demo started. Alarm incidents will appear shortly.')
      await refreshWorkspace().catch(() => undefined)
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not start the demo.')
    } finally {
      setIsDemoStarting(false)
    }
  }, [refreshWorkspace])

  /** Page-open demo start: skipped when a demo ran recently, silent on any failure. */
  const autoStartDemo = useCallback(async () => {
    try {
      const run = await api.startDemoRun(true)
      if (run.started) await refreshWorkspace().catch(() => undefined)
    } catch {
    }
  }, [refreshWorkspace])

  const createIncident = useCallback(async (data: Pick<Incident, 'title' | 'description' | 'priority'>) => {
    try {
      const incident = await api.createIncident(data)
      setIncidents((items) => [incident, ...items])
      setSelectedIncident(incident)
      setStatusMessage('Incident created. You can now start an investigation.')
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not create incident.')
      throw error
    }
  }, [])

  /** The operator confirms the problem is fixed; the incident moves to the Resolved list. */
  const resolveIncident = useCallback(async (incidentId: string) => {
    try {
      const resolved = await api.resolveIncident(incidentId)
      setIncidents((items) => items.map((item) => item.id === resolved.id ? resolved : item))
      setSelectedIncident((current) => current?.id === resolved.id ? resolved : current)
      setStatusMessage(`Incident resolved: ${resolved.title}`)
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not resolve the incident.')
    }
  }, [])

  /** Submit an operator-reviewed lesson for curated long-term memory indexing. */
  const confirmIncidentLesson = useCallback(async (data: IncidentLessonConfirmation) => {
    try {
      const lesson = await api.confirmIncidentLesson(data.investigation_id, data)
      setStatusMessage(lesson.state === 'CONFIRMED' ? 'Confirmed lesson added to incident memory.' : 'Incident lesson indexing failed.')
      return lesson
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not confirm the incident lesson.')
      throw error
    }
  }, [])

  const startInvestigation = useCallback(async () => {
    if (!selectedIncident || startInFlight.current) return null
    startInFlight.current = true
    setIsStartingInvestigation(true)
    setStatusMessage('Queueing the investigation…')
    try {
      const investigation = await api.startInvestigation(selectedIncident.id, selectedIncident.description)
      setSelectedInvestigation(investigation)
      localRows.current.set(investigation.id, investigation)
      setInvestigations((items) => [investigation, ...items.filter((item) => item.id !== investigation.id)])
      setStatusMessage('Investigation queued…')
      return investigation
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        const items = await refreshInvestigations().catch(() => [] as Investigation[])
        const active = items.find((item) => item.incident_id === selectedIncident.id
          && (item.lifecycle === 'PENDING' || item.lifecycle === 'RUNNING'))
        if (active) setSelectedInvestigation(active)
        setStatusMessage(error.message)
        return null
      }
      setStatusMessage(error instanceof Error ? error.message : 'Investigation failed.')
      await refreshInvestigations().catch(() => undefined)
      return null
    } finally {
      startInFlight.current = false
      setIsStartingInvestigation(false)
    }
  }, [refreshInvestigations, selectedIncident])

  /** Resume the durable workflow after an explicit operator decision. */
  const resolveHumanReview = useCallback(async (investigation: Investigation, decision: HumanReviewDecision) => {
    setStatusMessage('Resuming the investigation with the operator decision…')
    try {
      const updated = await api.resolveHumanReview(investigation.id, decision)
      setInvestigations((items) => items.map((item) => item.id === updated.id && isNewer(updated, item) ? updated : item))
      setSelectedInvestigation((item) => item?.id === updated.id && isNewer(updated, item) ? updated : item)
      setStatusMessage(updated.lifecycle === 'PENDING' ? 'Investigation queued…' : (LIFECYCLE_MESSAGES[updated.lifecycle] ?? `Investigation is ${updated.lifecycle.toLowerCase()}.`))
      await refreshWorkspace()
      return updated
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not resume the investigation.')
      throw error
    }
  }, [refreshWorkspace])

  useEffect(() => {
    setSelectedInvestigation((current) => {
      const fresh = current && investigations.find((item) => item.id === current.id)
      return fresh && isNewer(fresh, current) ? fresh : current
    })
  }, [investigations])

  const lastSeen = useRef<{ id: string, lifecycle: string } | null>(null)
  useEffect(() => {
    const previous = lastSeen.current
    lastSeen.current = selectedInvestigation
      ? { id: selectedInvestigation.id, lifecycle: selectedInvestigation.lifecycle }
      : null
    if (!selectedInvestigation || previous?.id !== selectedInvestigation.id) return
    if (previous.lifecycle === selectedInvestigation.lifecycle) return
    const message = LIFECYCLE_MESSAGES[selectedInvestigation.lifecycle]
    if (message) setStatusMessage(message)
  }, [selectedInvestigation])

  const activeId = selectedInvestigation
    && (selectedInvestigation.lifecycle === 'PENDING' || selectedInvestigation.lifecycle === 'RUNNING')
    ? selectedInvestigation.id : null
  useEffect(() => {
    if (!activeId) return
    const timer = window.setInterval(() => {
      void api.getInvestigation(activeId).then((fresh) => {
        setInvestigations((items) => items.map((item) => item.id === fresh.id && isNewer(fresh, item) ? fresh : item))
        setSelectedInvestigation((current) => current?.id === fresh.id && isNewer(fresh, current) ? fresh : current)
      }).catch(() => undefined)
    }, ACTIVE_INVESTIGATION_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [activeId])

  const selectInvestigation = useCallback((investigation: Investigation) => {
    setSelectedInvestigation(investigation)
  }, [])

  const metrics = useMemo(() => ({
    incidentCount: activeIncidents(incidents).length,
    resolvedIncidentCount: resolvedIncidents(incidents).length,
    runningInvestigationCount: investigations.filter((item) => item.lifecycle === 'RUNNING').length,
    pendingApprovalCount: investigations.filter((item) => item.lifecycle === 'AWAITING_HUMAN_REVIEW').length,
  }), [incidents, investigations])

  return {
    confirmIncidentLesson,
    autoStartDemo,
    createIncident,
    demoEnabled,
    incidents,
    investigations,
    isDemoStarting,
    isLoading,
    isStartingInvestigation,
    metrics,
    operationalMetrics,
    readiness,
    refreshWorkspace,
    resolveHumanReview,
    resolveIncident,
    selectedIncident,
    selectedInvestigation,
    setSelectedIncident,
    selectInvestigation,
    startDemoRun,
    startInvestigation,
    statusMessage,
  }
}
