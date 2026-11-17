"""Incident use cases called by the API routes."""

from uuid import UUID

from incidentflow.domain.incidents.models import (
    Incident,
    IncidentCreate,
    IncidentUpdate,
)
from incidentflow.infrastructure.database.incident_repository import (
    IncidentRepository,
)


class IncidentService:
    """Create, read, edit, resolve, and delete incidents."""

    def __init__(self, repository: IncidentRepository) -> None:
        self.repository = repository

    def create_incident(
        self,
        data: IncidentCreate,
    ) -> Incident:
        return self.repository.create_incident(data)

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

    def resolve_incident(self, incident_id: UUID) -> Incident | None:
        """Mark an incident resolved once the operator confirms the fix."""
        return self.repository.resolve_incident(incident_id)

    def delete_incident(self, incident_id: UUID) -> bool:
        return self.repository.delete_incident(incident_id)
