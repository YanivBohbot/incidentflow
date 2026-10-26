from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from incidentflow.agent.orchestration.investigation_workflow import build_investigation_workflow
from incidentflow.application.services.investigation_service import InvestigationService
from incidentflow.domain.investigations.models import Investigation, InvestigationStart
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import InvestigationRepository
from incidentflow.infrastructure.database.session import SessionLocal


def get_db_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def get_investigation_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> InvestigationService:
    return InvestigationService(
        InvestigationRepository(session),
        IncidentRepository(session),
        build_investigation_workflow(),
    )


InvestigationServiceDep = Annotated[InvestigationService, Depends(get_investigation_service)]

router = APIRouter(prefix="/investigations", tags=["Investigations"])


@router.get("", response_model=list[Investigation])
def list_investigations(service: InvestigationServiceDep) -> list[Investigation]:
    return service.list_investigations()


@router.post("", response_model=Investigation, status_code=status.HTTP_201_CREATED)
def start_investigation(
    data: InvestigationStart, service: InvestigationServiceDep
) -> Investigation:
    investigation = service.start_investigation(data)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return investigation


@router.get("/{investigation_id}", response_model=Investigation)
def get_investigation(investigation_id: UUID, service: InvestigationServiceDep) -> Investigation:
    investigation = service.get_investigation(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation
