import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Incident, Investigation, JiraCommentProposalInput, JiraIssueProposalInput, JiraProposal } from '../api'

export function useIncidentFlow() {
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [investigations, setInvestigations] = useState<Investigation[]>([])
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [selectedInvestigation, setSelectedInvestigation] = useState<Investigation | null>(null)
  const [proposals, setProposals] = useState<JiraProposal[]>([])
  const [statusMessage, setStatusMessage] = useState('Connecting to the IncidentFlow API…')
  const [isLoading, setIsLoading] = useState(true)

  const refreshInvestigations = useCallback(async () => {
    const items = await api.listInvestigations()
    setInvestigations(items)
    return items
  }, [])

  useEffect(() => {
    let isCurrent = true
    async function loadWorkspace() {
      try {
        const [incidentItems, investigationItems] = await Promise.all([api.listIncidents(), api.listInvestigations()])
        if (!isCurrent) return
        setIncidents(incidentItems)
        setInvestigations(investigationItems)
        setStatusMessage('API connected')
      } catch (error) {
        if (isCurrent) setStatusMessage(error instanceof Error ? error.message : 'Could not connect to the API.')
      } finally {
        if (isCurrent) setIsLoading(false)
      }
    }
    void loadWorkspace()
    return () => { isCurrent = false }
  }, [])

  useEffect(() => {
    if (!selectedInvestigation) return
    let isCurrent = true
    void api.listJiraProposals(selectedInvestigation.id)
      .then((items) => { if (isCurrent) setProposals(items) })
      .catch((error: unknown) => { if (isCurrent) setStatusMessage(error instanceof Error ? error.message : 'Could not load Jira proposals.') })
    return () => { isCurrent = false }
  }, [selectedInvestigation])

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

  const startInvestigation = useCallback(async () => {
    if (!selectedIncident) return null
    setStatusMessage('Running the investigation workflow…')
    try {
      const investigation = await api.startInvestigation(selectedIncident.id, selectedIncident.description)
      setSelectedInvestigation(investigation)
      setInvestigations((items) => [investigation, ...items.filter((item) => item.id !== investigation.id)])
      setStatusMessage(investigation.lifecycle === 'COMPLETED' ? 'Investigation completed.' : 'Investigation finished with a failure.')
      return investigation
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Investigation failed.')
      await refreshInvestigations()
      return null
    }
  }, [refreshInvestigations, selectedIncident])

  const approveProposal = useCallback(async (proposal: JiraProposal) => {
    setStatusMessage('Executing the approved Jira action…')
    try {
      const updated = await api.approveJiraProposal(proposal.id)
      setProposals((items) => items.map((item) => item.id === updated.id ? updated : item))
      setStatusMessage(updated.state === 'EXECUTED' ? 'Jira action executed.' : `Jira action failed: ${updated.error_message ?? 'Unknown error.'}`)
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not approve the Jira action.')
    }
  }, [])

  const rejectProposal = useCallback(async (proposal: JiraProposal, reason: string) => {
    try {
      const updated = await api.rejectJiraProposal(proposal.id, { actor: 'local-operator', reason: reason || undefined })
      setProposals((items) => items.map((item) => item.id === updated.id ? updated : item))
      setStatusMessage('Jira proposal rejected. Jira was not contacted.')
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not reject the Jira proposal.')
    }
  }, [])

  const cancelProposal = useCallback(async (proposal: JiraProposal, reason: string) => {
    try {
      const updated = await api.cancelJiraProposal(proposal.id, { actor: 'local-operator', reason: reason || undefined })
      setProposals((items) => items.map((item) => item.id === updated.id ? updated : item))
      setStatusMessage('Jira proposal cancelled. Jira was not contacted.')
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not cancel the Jira proposal.')
    }
  }, [])

  const proposeJiraIssue = useCallback(async (data: JiraIssueProposalInput) => {
    if (!selectedInvestigation) return
    try {
      const proposal = await api.proposeJiraIssue(selectedInvestigation.id, data)
      setProposals((items) => [proposal, ...items])
      setStatusMessage('Jira issue proposal saved. Awaiting human approval.')
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not save the Jira issue proposal.')
      throw error
    }
  }, [selectedInvestigation])

  const proposeJiraComment = useCallback(async (data: JiraCommentProposalInput) => {
    if (!selectedInvestigation) return
    try {
      const proposal = await api.proposeJiraComment(selectedInvestigation.id, data)
      setProposals((items) => [proposal, ...items])
      setStatusMessage('Jira comment proposal saved. Awaiting human approval.')
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : 'Could not save the Jira comment proposal.')
      throw error
    }
  }, [selectedInvestigation])

  const selectInvestigation = useCallback((investigation: Investigation) => {
    setSelectedInvestigation(investigation)
    setProposals([])
  }, [])

  const metrics = useMemo(() => ({
    incidentCount: incidents.length,
    runningInvestigationCount: investigations.filter((item) => item.lifecycle === 'RUNNING').length,
    pendingApprovalCount: proposals.filter((proposal) => proposal.state === 'PENDING').length,
  }), [incidents, investigations, proposals])

  return {
    approveProposal,
    cancelProposal,
    createIncident,
    incidents,
    investigations,
    isLoading,
    metrics,
    proposeJiraComment,
    proposeJiraIssue,
    proposals,
    rejectProposal,
    selectedIncident,
    selectedInvestigation,
    setSelectedIncident,
    selectInvestigation,
    startInvestigation,
    statusMessage,
  }
}
