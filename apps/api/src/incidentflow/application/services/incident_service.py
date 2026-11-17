"""Incident use cases called by the API routes."""

from uuid import UUID

from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.incidents.models import (
    Incident,
    IncidentCreate,
    IncidentStatus,
    IncidentUpdate,
)
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_repository import (
    IncidentRepository,
)


class IncidentService:
    """Create, read, edit, resolve, and delete incidents."""

    def __init__(
        self, repository: IncidentRepository, *, events: IncidentEventRepository | None = None
    ) -> None:
        self.repository = repository
        self.events = events

    def create_incident(self, data: IncidentCreate, *, actor: str = "system") -> Incident:
        incident = self.repository.create_incident(data)
        if self.events is not None:
            self.events.record(
                IncidentEventKind.INCIDENT_CREATED,
                incident_id=incident.id,
                actor=actor,
                summary=f"Incident reported by {actor}",
                details={"source": incident.source.value},
            )
        return incident

    def get_incident(
        self,
        incident_id: UUID,
    ) -> Incident | None:
        return self.repository.get_incident(incident_id)

    def list_incidents(self) -> list[Incident]:
        return self.repository.list_incidents()

    def update_incident(
        self,
        incident_id: UUID,
        data: IncidentUpdate,
    ) -> Incident | None:
        return self.repository.update_incident(incident_id, data)

    def resolve_incident(self, incident_id: UUID, *, actor: str = "system") -> Incident | None:
        """Mark an incident resolved once the operator confirms the fix."""
        before = self.repository.get_incident(incident_id)
        incident = self.repository.resolve_incident(incident_id)
        changed = before is not None and before.status is not IncidentStatus.RESOLVED
        if incident is not None and changed and self.events is not None:
            self.events.record(
                IncidentEventKind.INCIDENT_RESOLVED,
                incident_id=incident.id,
                actor=actor,
                summary=f"Marked resolved by {actor}",
            )
        return incident

    def delete_incident(self, incident_id: UUID) -> bool:
        return self.repository.delete_incident(incident_id)
