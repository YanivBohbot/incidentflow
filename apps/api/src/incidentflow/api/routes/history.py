"""History endpoints: the decision timeline and the journal of one incident (read-only)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from incidentflow.api.routes.incidents import CAN_READ, get_db_session
from incidentflow.domain.history.models import IncidentEvent, IncidentEventKind, IncidentEventPage
from incidentflow.infrastructure.database.incident_event_repository import (
    MAX_PAGE_SIZE,
    IncidentEventRepository,
    decode_cursor,
)


def get_event_repository(
    session: Annotated[Session, Depends(get_db_session)],
) -> IncidentEventRepository:
    """Open the event repository on the request's database session."""
    return IncidentEventRepository(session)


EventRepositoryDep = Annotated[IncidentEventRepository, Depends(get_event_repository)]

router = APIRouter(tags=["History"])


def _parse_kinds(kinds: str | None) -> list[IncidentEventKind] | None:
    if not kinds:
        return None
    try:
        return [IncidentEventKind(kind.strip()) for kind in kinds.split(",") if kind.strip()]
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


@router.get("/history", response_model=IncidentEventPage, dependencies=CAN_READ)
def list_history(
    events: EventRepositoryDep,
    incident_id: UUID | None = None,
    category: str | None = Query(default=None, description="Incident service, or title."),
    hide_untouched: bool = Query(default=False, description="Drop closed, uninvestigated."),
    kinds: str | None = Query(default=None, description="Comma-separated event kinds."),
    before: str | None = Query(default=None, description="next_before of the previous page."),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
) -> IncidentEventPage:
    """Return events newest first, optionally for one incident or some kinds."""
    if before:
        try:
            decode_cursor(before)
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor.") from error
    return events.list_history(
        incident_id=incident_id,
        kinds=_parse_kinds(kinds),
        category=category,
        hide_untouched=hide_untouched,
        before=before,
        limit=limit,
    )


@router.get(
    "/incidents/{incident_id}/events", response_model=list[IncidentEvent], dependencies=CAN_READ
)
def list_incident_events(incident_id: UUID, events: EventRepositoryDep) -> list[IncidentEvent]:
    """Return the journal of one incident, oldest first."""
    if not events.incident_exists(incident_id):
        raise HTTPException(status_code=404, detail="Incident not found")
    return events.list_for_incident(incident_id)
