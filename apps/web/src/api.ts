export type Incident = {
  id: string
  title: string
  description: string
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  status: string
  created_at: string
  updated_at: string
}

export type InvestigationEvidence = {
  source: string
  detail: string
  source_status: string
}

export type InvestigationReport = {
  summary: string
  confidence: number
  agents_consulted?: string[]
  evidence?: InvestigationEvidence[]
  hypotheses?: string[]
  proposed_actions?: string[]
  limitations?: string[]
}

export type Investigation = {
  id: string
  incident_id: string
  lifecycle: string
  report: InvestigationReport | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export type JiraProposal = {
  id: string
  investigation_id: string
  action: 'CREATE_ISSUE' | 'ADD_COMMENT'
  state: 'PENDING' | 'EXECUTING' | 'EXECUTED' | 'FAILED' | 'REJECTED'
  payload: Record<string, string>
  result_payload: { operation: string; result: unknown } | null
  error_message: string | null
  approved_at: string | null
  approved_by: string | null
  rejected_at: string | null
  rejected_by: string | null
  rejection_reason: string | null
  cancelled_at: string | null
  cancelled_by: string | null
  cancellation_reason: string | null
  proposed_by: string
  decision_history: Array<{ event: string; actor: string; at: string; reason?: string }>
}

export type JiraResourceOption = { cloud_id: string; url: string | null }
export type JiraProjectOption = { key: string; name: string }
export type JiraIssueTypeOption = { id: string; name: string }
export type JiraProposalDecision = { actor: string; reason?: string }

export type JiraIssueProposalInput = {
  cloudId: string
  projectKey: string
  issueType: string
  summary: string
  description: string
}

export type JiraCommentProposalInput = {
  cloudId: string
  issueIdOrKey: string
  commentBody: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail ?? `IncidentFlow API request failed (HTTP ${response.status}).`)
  }
  return response.json().catch(() => { throw new Error('IncidentFlow API returned an invalid response.') }) as Promise<T>
}

export const api = {
  listIncidents: () => request<Incident[]>('/incidents'),
  createIncident: (data: Pick<Incident, 'title' | 'description' | 'priority'>) =>
    request<Incident>('/incidents', { method: 'POST', body: JSON.stringify(data) }),
  startInvestigation: (incidentId: string, incidentRequest: string) =>
    request<Investigation>('/investigations', {
      method: 'POST',
      body: JSON.stringify({ incident_id: incidentId, incident_request: incidentRequest }),
    }),
  listInvestigations: () => request<Investigation[]>('/investigations'),
  listJiraProposals: (investigationId: string) =>
    request<JiraProposal[]>(`/jira/investigations/${investigationId}/proposals`),
  listJiraResources: () => request<JiraResourceOption[]>('/jira/catalog/resources'),
  listJiraProjects: (cloudId: string) => request<JiraProjectOption[]>(`/jira/catalog/projects?cloud_id=${encodeURIComponent(cloudId)}`),
  listJiraIssueTypes: (cloudId: string, projectKey: string) => request<JiraIssueTypeOption[]>(`/jira/catalog/projects/${encodeURIComponent(projectKey)}/issue-types?cloud_id=${encodeURIComponent(cloudId)}`),
  proposeJiraIssue: (investigationId: string, data: JiraIssueProposalInput) =>
    request<JiraProposal>(`/jira/investigations/${investigationId}/issues`, { method: 'POST', body: JSON.stringify(data) }),
  proposeJiraComment: (investigationId: string, data: JiraCommentProposalInput) =>
    request<JiraProposal>(`/jira/investigations/${investigationId}/comments`, { method: 'POST', body: JSON.stringify(data) }),
  approveJiraProposal: (proposalId: string) =>
    request<JiraProposal>(`/jira/proposals/${proposalId}/approve`, { method: 'POST' }),
  rejectJiraProposal: (proposalId: string, decision: JiraProposalDecision) =>
    request<JiraProposal>(`/jira/proposals/${proposalId}/reject`, { method: 'POST', body: JSON.stringify(decision) }),
  cancelJiraProposal: (proposalId: string, decision: JiraProposalDecision) =>
    request<JiraProposal>(`/jira/proposals/${proposalId}/cancel`, { method: 'POST', body: JSON.stringify(decision) }),
}
