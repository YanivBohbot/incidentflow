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
}
