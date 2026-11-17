from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.application.history_backfill import backfill
from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.incidents.models import IncidentCreate, IncidentStatus
from incidentflow.domain.investigations.models import (
    InvestigationCreate,
    InvestigationLifecycle,
    InvestigationTraceStep,
)
from incidentflow.domain.memory.models import IncidentLessonConfirmation
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_lesson_repository import (
    IncidentLessonRepository,
)
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM, InvestigationORM


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def seed(session: Session):
    incident = IncidentRepository(session).create_incident(
        IncidentCreate(title="Checkout down", description="checkout-api returns HTTP 503.")
    )
    investigation = InvestigationRepository(session).create_investigation(
        InvestigationCreate(
            incident_id=incident.id,
            incident_request="Investigate checkout.",
            incident_business_status="OPEN",
        )
    )
    orm = session.get(InvestigationORM, investigation.id)
    orm.lifecycle = InvestigationLifecycle.COMPLETED
    orm.report_payload = {"summary": "Pool exhausted.", "confidence": 0.7, "root_cause": "Pool."}
    session.get(IncidentORM, incident.id).status = IncidentStatus.RESOLVED
    session.commit()
    lessons = IncidentLessonRepository(session)
    lesson = lessons.create_pending(
        IncidentLessonConfirmation(
            investigation_id=investigation.id,
            service="checkout-api",
            environment="production",
            confirmed_root_cause="Pool exhausted.",
            validated_resolution="Raised the pool size.",
        )
    )
    lessons.mark_confirmed(lesson.id, "vector-1")
    return incident, investigation


def no_trace(investigation_id: UUID) -> list[InvestigationTraceStep]:
    return []


def jira_trace(investigation_id: UUID) -> list[InvestigationTraceStep]:
    return [
        InvestigationTraceStep(
            kind="review_pause",
            actor="Human-in-the-loop middleware",
            title="Paused before createJiraIssue",
            detail="Create the tracking issue.",
            status="info",
            data={"review_type": "JIRA_WRITE", "tool_name": "createJiraIssue"},
        ),
        InvestigationTraceStep(
            kind="review_decision",
            actor="Operator (alice)",
            title="Operator approved",
            detail="Looks right",
            status="approved",
            data={},
        ),
    ]


def test_backfill_reconstructs_incident_journal(session) -> None:
    incident, _ = seed(session)

    inserted = backfill(session, trace_reader=no_trace)

    journal = IncidentEventRepository(session).list_for_incident(incident.id)
    assert inserted == len(journal)
    assert [item.kind for item in journal[:3]] == [
        IncidentEventKind.INCIDENT_CREATED,
        IncidentEventKind.INVESTIGATION_STARTED,
        IncidentEventKind.INVESTIGATION_COMPLETED,
    ]
    assert {item.kind for item in journal[3:]} == {
        IncidentEventKind.LESSON_SAVED,
        IncidentEventKind.INCIDENT_RESOLVED,
    }
    assert all(item.reconstructed for item in journal)
    resolved = next(item for item in journal if item.kind is IncidentEventKind.INCIDENT_RESOLVED)
    assert resolved.actor == "unknown"
    assert journal[2].details["confidence"] == 0.7


def test_backfill_adds_review_events_from_the_trace(session) -> None:
    incident, _ = seed(session)

    backfill(session, trace_reader=jira_trace)

    journal = IncidentEventRepository(session).list_for_incident(incident.id)
    reviews = [item for item in journal if item.kind.value.startswith("REVIEW_")]
    assert [item.kind for item in reviews] == [
        IncidentEventKind.REVIEW_REQUESTED,
        IncidentEventKind.REVIEW_DECIDED,
    ]
    assert reviews[1].actor == "alice"
    assert reviews[1].details["decision"] == "APPROVE"
    assert reviews[1].details["tool_name"] == "createJiraIssue"


def test_second_backfill_inserts_nothing(session) -> None:
    seed(session)
    backfill(session, trace_reader=no_trace)

    assert backfill(session, trace_reader=no_trace) == 0


def test_backfill_keeps_live_events_and_fills_what_is_missing(session) -> None:
    incident, investigation = seed(session)
    events = IncidentEventRepository(session)
    events.record(IncidentEventKind.INCIDENT_CREATED, incident_id=incident.id, summary="Live")
    events.record(
        IncidentEventKind.INCIDENT_RESOLVED, incident_id=incident.id, summary="Live", actor="alice"
    )

    backfill(session, trace_reader=no_trace)

    journal = events.list_for_incident(incident.id)
    created = [item for item in journal if item.kind is IncidentEventKind.INCIDENT_CREATED]
    resolved = [item for item in journal if item.kind is IncidentEventKind.INCIDENT_RESOLVED]
    assert [item.reconstructed for item in created] == [False]
    assert [item.actor for item in resolved] == ["alice"]
    assert {item.kind for item in journal if item.investigation_id == investigation.id} == {
        IncidentEventKind.INVESTIGATION_STARTED,
        IncidentEventKind.INVESTIGATION_COMPLETED,
        IncidentEventKind.LESSON_SAVED,
    }


def test_backfill_skips_an_investigation_that_already_has_live_events(session) -> None:
    incident, investigation = seed(session)
    events = IncidentEventRepository(session)
    events.record(
        IncidentEventKind.INVESTIGATION_STARTED,
        incident_id=incident.id,
        investigation_id=investigation.id,
        summary="Live",
    )

    backfill(session, trace_reader=no_trace)

    starts = [
        item
        for item in events.list_for_incident(incident.id)
        if item.kind is IncidentEventKind.INVESTIGATION_STARTED
    ]
    assert [item.reconstructed for item in starts] == [False]
