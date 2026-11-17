"""Incident endpoints: create, list, edit, resolve, and delete incidents."""

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from incidentflow.application.services.incident_service import (
    IncidentService,
)
from incidentflow.core.auth import OperatorPrincipal, require_operator, require_viewer
from incidentflow.domain.incidents.models import (
    Incident,
    IncidentCreate,
    IncidentUpdate,
)
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_repository import (
    IncidentRepository,
)
from incidentflow.infrastructure.database.session import SessionLocal


def get_db_session() -> Iterator[Session]:
    """Open one database session per request."""
    with SessionLocal() as session:
        yield session


def get_incident_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> IncidentService:
    repository = IncidentRepository(session)
    return IncidentService(repository, events=IncidentEventRepository(session))


IncidentServiceDep = Annotated[IncidentService, Depends(get_incident_service)]
CAN_READ = [Depends(require_viewer)]
CAN_OPERATE = [Depends(require_operator)]


router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.post(
    "",
    response_model=Incident,
    status_code=status.HTTP_201_CREATED,
    dependencies=CAN_OPERATE,
)
def create_incident(
    data: IncidentCreate,
    service: IncidentServiceDep,
    principal: OperatorPrincipal,
) -> Incident:
    """Record an incident reported by an operator."""
    return service.create_incident(data, actor=principal.username)


@router.get("", response_model=list[Incident], dependencies=CAN_READ)
def list_incidents(
    service: IncidentServiceDep,
) -> list[Incident]:
    """Return every incident, open and closed."""
    return service.list_incidents()


@router.get("/{incident_id}", response_model=Incident, dependencies=CAN_READ)
def get_incident(
    incident_id: UUID,
    service: IncidentServiceDep,
) -> Incident:
    """Return one incident or 404."""
    incident = service.get_incident(incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return incident


@router.patch("/{incident_id}", response_model=Incident, dependencies=CAN_OPERATE)
def update_incident(
    incident_id: UUID,
    data: IncidentUpdate,
    service: IncidentServiceDep,
) -> Incident:
    """Edit the title, description, or priority of an incident."""
    incident = service.update_incident(incident_id, data)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return incident


@router.post("/{incident_id}/resolve", response_model=Incident, dependencies=CAN_OPERATE)
def resolve_incident(
    incident_id: UUID, service: IncidentServiceDep, principal: OperatorPrincipal
) -> Incident:
    """An operator confirms the problem is fixed; the incident leaves the open queue."""
    incident = service.resolve_incident(incident_id, actor=principal.username)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=CAN_OPERATE,
)
def delete_incident(
    incident_id: UUID,
    service: IncidentServiceDep,
) -> None:
    """Delete an incident."""
    deleted = service.delete_incident(incident_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )
