from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from incidentflow.application.services.incident_lesson_service import IncidentLessonService
from incidentflow.application.services.investigation_service import InvestigationService
from incidentflow.core.config import get_settings
from incidentflow.domain.human_review.models import HumanReviewDecision
from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationStart,
    InvestigationTraceStep,
)
from incidentflow.domain.memory.models import IncidentLesson, IncidentLessonConfirmation
from incidentflow.infrastructure.database.incident_lesson_repository import IncidentLessonRepository
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import InvestigationRepository
from incidentflow.infrastructure.database.session import SessionLocal
from incidentflow.knowledge.resolved_incident_store import ResolvedIncidentStore


def get_db_session() -> Iterator[Session]:
    """Provide one database session for the duration of an API request."""
    with SessionLocal() as session:
        yield session


def get_investigation_service(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> InvestigationService:
    """Build the investigation service with the lifespan-owned workflow."""
    return InvestigationService(
        InvestigationRepository(session),
        IncidentRepository(session),
        request.app.state.investigation_workflow,
        request.app.state.operational_metrics,
    )


def get_incident_lesson_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> IncidentLessonService:
    """Build the explicit confirmation service only when curated memory is enabled."""
    settings = get_settings()
    if not settings.pinecone_resolved_incidents_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Resolved incident memory is not enabled.",
        )
    return IncidentLessonService(
        IncidentLessonRepository(session),
        ResolvedIncidentStore.from_settings(settings),
    )


InvestigationServiceDep = Annotated[InvestigationService, Depends(get_investigation_service)]
IncidentLessonServiceDep = Annotated[IncidentLessonService, Depends(get_incident_lesson_service)]

router = APIRouter(prefix="/investigations", tags=["Investigations"])


@router.get("", response_model=list[Investigation])
def list_investigations(service: InvestigationServiceDep) -> list[Investigation]:
    """Return investigations in their persisted operational order."""
    return service.list_investigations()


@router.post("", response_model=Investigation, status_code=status.HTTP_201_CREATED)
async def start_investigation(
    data: InvestigationStart, service: InvestigationServiceDep
) -> Investigation:
    """Start an investigation for an existing incident and return its final record."""
    investigation = await service.start_investigation(data)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return investigation


@router.get("/{investigation_id}", response_model=Investigation)
def get_investigation(investigation_id: UUID, service: InvestigationServiceDep) -> Investigation:
    """Return one investigation or a clear 404 when it is absent."""
    investigation = service.get_investigation(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation


@router.get("/{investigation_id}/trace", response_model=list[InvestigationTraceStep])
async def get_investigation_trace(
    investigation_id: UUID, service: InvestigationServiceDep
) -> list[InvestigationTraceStep]:
    """Return the readable multi-agent timeline: delegations, findings, reviews, report."""
    trace = await service.get_investigation_trace(investigation_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return trace


@router.post("/{investigation_id}/human-review/resolve", response_model=Investigation)
async def resolve_human_review(
    investigation_id: UUID,
    decision: HumanReviewDecision,
    service: InvestigationServiceDep,
) -> Investigation:
    """Resume one paused investigation with an explicit authenticated-operator decision."""
    try:
        investigation = await service.resume_human_review(investigation_id, decision)
    except ValueError as error:  # an edit outside the permitted Jira fields
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Investigation is not awaiting a human review.",
        )
    return investigation


@router.post(
    "/{investigation_id}/memory-lessons",
    response_model=IncidentLesson,
    status_code=status.HTTP_201_CREATED,
)
def confirm_incident_lesson(
    investigation_id: UUID,
    data: IncidentLessonConfirmation,
    investigation_service: InvestigationServiceDep,
    lesson_service: IncidentLessonServiceDep,
) -> IncidentLesson:
    """Index an operator-reviewed lesson after its source investigation is complete."""
    if data.investigation_id != investigation_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The lesson investigation_id must match the URL.",
        )
    if investigation_service.get_investigation(investigation_id) is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    try:
        return lesson_service.confirm_and_index(data)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
