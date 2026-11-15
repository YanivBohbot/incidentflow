import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import type {
  HumanReviewDecision,
  Incident,
  IncidentLessonConfirmation,
  Investigation,
  OperationalMetrics,
  Readiness,
} from '../api'

const WORKSPACE_REFRESH_MS = 10_000
const ACTIVE_INVESTIGATION_REFRESH_MS = 1_500

const LIFECYCLE_MESSAGES: Record<string, string> = {
  RUNNING: 'Investigation running…',
  COMPLETED: 'Investigation completed.',
  AWAITING_HUMAN_REVIEW: 'Investigation paused for a human decision.',
  FAILED: 'Investigation finished with a failure.',
}

export function useIncidentFlow() {
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

  const refreshInvestigations = useCallback(async () => {
    const items = await api.listInvestigations()
    setInvestigations(items)
    return items
  }, [])

  const refreshWorkspace = useCallback(async () => {
    const [incidentItems, investigationItems, readinessSnapshot, metricsSnapshot] = await Promise.all([
      api.listIncidents(),
      api.listInvestigations(),
      api.getReadiness(),
      api.getOperationalMetrics(),
    ])
    setIncidents(incidentItems)
    setInvestigations(investigationItems)
    setReadiness(readinessSnapshot)
    setOperationalMetrics(metricsSnapshot)
    return { incidentItems, investigationItems }
  }, [])

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
    // Investigations can pause from anywhere (another tab, the API, a script): refresh
    // regularly so the approval badge and banner appear without reloading the page.
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refreshWorkspace().catch(() => undefined)
    }, WORKSPACE_REFRESH_MS)
    const refreshOnFocus = () => {
      if (document.visibilityState === 'visible') void refreshWorkspace().catch(() => undefined)
    }
    document.addEventListener('visibilitychange', refreshOnFocus)
    return () => {
      isCurrent = false
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refreshOnFocus)
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
    if (!selectedIncident) return null
    setStatusMessage('Queueing the investigation…')
    try {
      // The API answers 202 with a PENDING investigation; a worker runs it, and polling
      // (below) follows it through RUNNING to its final or paused state.
      const investigation = await api.startInvestigation(selectedIncident.id, selectedIncident.description)
      setSelectedInvestigation(investigation)
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
    }
  }, [refreshInvestigations, selectedIncident])

  /** Resume the durable workflow after an explicit operator decision. */
  const resolveHumanReview = useCallback(async (investigation: Investigation, decision: HumanReviewDecision) => {
    setStatusMessage('Resuming the investigation with the operator decision…')
    try {
      const updated = await api.resolveHumanReview(investigation.id, decision)
      setInvestigations((items) => items.map((item) => item.id === updated.id ? updated : item))
      setSelectedInvestigation((item) => item?.id === updated.id ? updated : item)
      setStatusMessage(updated.lifecycle === 'PENDING' ? 'Investigation queued…' : (LIFECYCLE_MESSAGES[updated.lifecycle] ?? `Investigation is ${updated.lifecycle.toLowerCase()}.`))
      await refreshWorkspace()
      return updated
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not resume the investigation.')
      throw error
    }
  }, [refreshWorkspace])

  // Keep the selected investigation in step with the polled list.
  useEffect(() => {
    setSelectedInvestigation((current) => {
      const fresh = current && investigations.find((item) => item.id === current.id)
      return fresh && fresh.updated_at !== current.updated_at ? fresh : current
    })
  }, [investigations])

  // Announce lifecycle transitions of the selected investigation once, not on every poll.
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

  // Faster feedback while the selected investigation is queued or running.
  const activeId = selectedInvestigation
    && (selectedInvestigation.lifecycle === 'PENDING' || selectedInvestigation.lifecycle === 'RUNNING')
    ? selectedInvestigation.id : null
  useEffect(() => {
    if (!activeId) return
    const timer = window.setInterval(() => {
      void api.getInvestigation(activeId).then((fresh) => {
        setInvestigations((items) => items.map((item) => item.id === fresh.id ? fresh : item))
        setSelectedInvestigation((current) => current?.id === fresh.id ? fresh : current)
      }).catch(() => undefined)
    }, ACTIVE_INVESTIGATION_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [activeId])

  const selectInvestigation = useCallback((investigation: Investigation) => {
    setSelectedInvestigation(investigation)
  }, [])

  const metrics = useMemo(() => ({
    incidentCount: incidents.length,
    runningInvestigationCount: investigations.filter((item) => item.lifecycle === 'RUNNING').length,
    pendingApprovalCount: investigations.filter((item) => item.lifecycle === 'AWAITING_HUMAN_REVIEW').length,
  }), [incidents, investigations])

  return {
    confirmIncidentLesson,
    createIncident,
    incidents,
    investigations,
    isLoading,
    metrics,
    operationalMetrics,
    readiness,
    refreshWorkspace,
    resolveHumanReview,
    selectedIncident,
    selectedInvestigation,
    setSelectedIncident,
    selectInvestigation,
    startInvestigation,
    statusMessage,
  }
}
