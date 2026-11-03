import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type {
  HumanReviewDecision,
  Incident,
  IncidentLessonConfirmation,
  Investigation,
  OperationalMetrics,
  Readiness,
} from '../api'

const WORKSPACE_REFRESH_MS = 10_000

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
    setStatusMessage('Running the investigation workflow…')
    // The start request returns only when the workflow finishes or pauses. Meanwhile, poll the
    // list so the RUNNING investigation appears and its agent trace can be followed live.
    const startedAt = Date.now()
    const poller = window.setInterval(() => {
      void api.listInvestigations().then((items) => {
        setInvestigations(items)
        const running = items.find((item) => item.incident_id === selectedIncident.id
          && item.lifecycle === 'RUNNING' && Date.parse(item.created_at) >= startedAt - 5000)
        if (running) setSelectedInvestigation((current) => current?.id === running.id ? current : running)
      }).catch(() => undefined)
    }, 1500)
    try {
      const investigation = await api.startInvestigation(selectedIncident.id, selectedIncident.description)
      setSelectedInvestigation(investigation)
      setInvestigations((items) => [investigation, ...items.filter((item) => item.id !== investigation.id)])
      setStatusMessage(
        investigation.lifecycle === 'COMPLETED'
          ? 'Investigation completed.'
          : investigation.lifecycle === 'AWAITING_HUMAN_REVIEW'
            ? 'Investigation paused for a human decision.'
            : 'Investigation finished with a failure.',
      )
      return investigation
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Investigation failed.')
      await refreshInvestigations()
      return null
    } finally {
      window.clearInterval(poller)
    }
  }, [refreshInvestigations, selectedIncident])

  /** Resume the durable workflow after an explicit operator decision. */
  const resolveHumanReview = useCallback(async (investigation: Investigation, decision: HumanReviewDecision) => {
    setStatusMessage('Resuming the investigation with the operator decision…')
    try {
      const updated = await api.resolveHumanReview(investigation.id, decision)
      setInvestigations((items) => items.map((item) => item.id === updated.id ? updated : item))
      setSelectedInvestigation((item) => item?.id === updated.id ? updated : item)
      setStatusMessage(updated.lifecycle === 'COMPLETED' ? 'Investigation completed.' : `Investigation is ${updated.lifecycle.toLowerCase()}.`)
      await refreshWorkspace()
      return updated
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not resume the investigation.')
      throw error
    }
  }, [refreshWorkspace])

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
