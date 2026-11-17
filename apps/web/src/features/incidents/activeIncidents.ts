import type { Incident } from '../../api'

const CLOSED_STATUSES = new Set(['CLOSED', 'RESOLVED'])

/** Closed incidents stay in the database but are hidden from the queue and its counts. */
export const isActiveIncident = (incident: Incident) => !CLOSED_STATUSES.has(incident.status)

export const activeIncidents = (incidents: Incident[]) => incidents.filter(isActiveIncident)

export const resolvedIncidents = (incidents: Incident[]) => incidents.filter((incident) => !isActiveIncident(incident))
