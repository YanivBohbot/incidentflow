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
  human_review: HumanReview | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export type HumanReview = {
  id: string
  review_type: 'JIRA_WRITE' | 'INSUFFICIENT_EVIDENCE' | 'CONFLICTING_EVIDENCE'
  reason: string
  evidence_references: string[]
  draft: Record<string, unknown>
}

export type HumanReviewDecision = {
  decision: 'APPROVE' | 'REJECT' | 'REQUEST_INFORMATION'
  actor: string
  reason?: string
  /** Only the Jira text fields listed in review.draft.editable_fields. */
  edited_draft?: Record<string, string>
}

export type IncidentLesson = {
  id: string
  investigation_id: string
  service: string
  environment: string
  confirmed_root_cause: string
  validated_resolution: string
  tenant_id: string | null
  state: 'PENDING_INDEX' | 'CONFIRMED' | 'INDEX_FAILED'
  vector_id: string | null
  index_error: string | null
  created_at: string
  confirmed_at: string | null
  updated_at: string
}

export type IncidentLessonConfirmation = Pick<
  IncidentLesson,
  'investigation_id' | 'service' | 'environment' | 'confirmed_root_cause' | 'validated_resolution' | 'tenant_id'
>

export type TraceStep = {
  kind: "request" | "reasoning" | "delegation" | "subagent_call" | "finding" | "limit" | "review_pause" | "review_decision" | "report"
  actor: string
  title: string
  detail: string
  status: "live" | "unavailable" | "pending" | "approved" | "rejected" | "info"
  confidence: number | null
  data: Record<string, unknown>
}

export type Readiness = {
  status: 'ready' | 'starting'
  checkpointer?: 'ready'
}

export type OperationalMetrics = {
  requests_by_status: Record<string, number>
  investigations_by_lifecycle: Record<string, number>
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

/** Read a non-versioned operational endpoint exposed outside the API prefix. */
async function requestOperational<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`Operational API request failed (HTTP ${response.status}).`)
  }
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
  resolveHumanReview: (investigationId: string, decision: HumanReviewDecision) =>
    request<Investigation>(`/investigations/${investigationId}/human-review/resolve`, {
      method: 'POST',
      body: JSON.stringify(decision),
    }),
  confirmIncidentLesson: (investigationId: string, data: IncidentLessonConfirmation) =>
    request<IncidentLesson>(`/investigations/${investigationId}/memory-lessons`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getInvestigationTrace: (investigationId: string) =>
    request<TraceStep[]>(`/investigations/${investigationId}/trace`),
  getOperationalMetrics: () => requestOperational<OperationalMetrics>('/operations/metrics'),
  getReadiness: () => requestOperational<Readiness>('/health/ready'),
}
