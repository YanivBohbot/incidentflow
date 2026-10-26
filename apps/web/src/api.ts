export type Incident = {
  id: string
  title: string
  description: string
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  status: string
}

export type Investigation = {
  id: string
  incident_id: string
  lifecycle: string
  report: { summary: string; confidence: number } | null
  error_message: string | null
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
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) throw new Error((await response.json()).detail ?? 'Request failed.')
  return response.json() as Promise<T>
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
  approveJiraProposal: (proposalId: string) =>
    request<JiraProposal>(`/jira/proposals/${proposalId}/approve`, { method: 'POST' }),
}
