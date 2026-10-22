from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from incidentflow.application.services.incident_service import (
    IncidentService,
)
from incidentflow.domain.incidents.models import (
    Incident,
    IncidentCreate,
    IncidentUpdate,
)
from incidentflow.infrastructure.database.incident_repository import (
    IncidentRepository,
)
from incidentflow.infrastructure.database.session import SessionLocal


def get_db_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def get_incident_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> IncidentService:
    repository = IncidentRepository(session)
    return IncidentService(repository)


IncidentServiceDep = Annotated[IncidentService, Depends(get_incident_service)]


router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.post(
    "",
    response_model=Incident,
    status_code=status.HTTP_201_CREATED,
)
def create_incident(
    data: IncidentCreate,
    service: IncidentServiceDep,
) -> Incident:
    return service.create_incident(data)


@router.get("", response_model=list[Incident])
def list_incidents(
    service: IncidentServiceDep,
) -> list[Incident]:
    return service.list_incidents()


@router.get("/{incident_id}", response_model=Incident)
def get_incident(
    incident_id: UUID,
    service: IncidentServiceDep,
) -> Incident:
    incident = service.get_incident(incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return incident


@router.patch("/{incident_id}", response_model=Incident)
def update_incident(
    incident_id: UUID,
    data: IncidentUpdate,
    service: IncidentServiceDep,
) -> Incident:
    incident = service.update_incident(incident_id, data)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return incident


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_incident(
    incident_id: UUID,
    service: IncidentServiceDep,
) -> None:
    deleted = service.delete_incident(incident_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )
