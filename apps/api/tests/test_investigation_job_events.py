from collections.abc import Iterator
from dataclasses import replace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.agent.findings import InvestigationEvidence, InvestigationReport
from incidentflow.application.jobs.processor import LeaseLostError, persist_workflow_result
from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.human_review.models import HumanReview, HumanReviewType
from incidentflow.domain.incidents.models import IncidentCreate
from incidentflow.domain.investigations.models import InvestigationCreate
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def events(session: Session) -> IncidentEventRepository:
    return IncidentEventRepository(session)


def claimed_investigation(session: Session):
    incident = IncidentRepository(session).create_incident(
        IncidentCreate(title="Checkout down", description="checkout-api returns HTTP 503.")
    )
    repository = InvestigationRepository(session)
    investigation = repository.create_investigation(
        InvestigationCreate(
            incident_id=incident.id,
            incident_request="Investigate checkout.",
            incident_business_status="OPEN",
        )
    )
    return repository, repository.claim(investigation.id, lease_seconds=60)


def report(**overrides) -> InvestigationReport:
    values = {
        "summary": "Checkout is down.",
        "confidence": 0.7,
        "root_cause": "The connection pool is exhausted.",
        "evidence": [
            InvestigationEvidence(
                source="ask_it_operations",
                detail="Created Jira issue SAM1-25 to track the outage.",
                source_status="live",
            )
        ],
    }
    return InvestigationReport(**{**values, **overrides})


def completed(found: InvestigationReport | None = None) -> dict:
    return {"investigation_lifecycle": "completed", "report": found or report()}


def test_completion_records_one_event_with_confidence(session, events) -> None:
    repository, claimed = claimed_investigation(session)

    persist_workflow_result(repository, claimed, completed(), events=events)

    [event] = events.list_history().events
    assert event.kind is IncidentEventKind.INVESTIGATION_COMPLETED
    assert event.investigation_id == claimed.investigation.id
    assert event.incident_id == claimed.investigation.incident_id
    assert event.details["confidence"] == 0.7
    assert event.details["root_cause"] == "The connection pool is exhausted."
    assert "jira_key" not in event.details


def test_completion_after_approved_jira_write_carries_the_issue_key(session, events) -> None:
    repository, claimed = claimed_investigation(session)
    events.record(
        IncidentEventKind.REVIEW_DECIDED,
        incident_id=claimed.investigation.incident_id,
        investigation_id=claimed.investigation.id,
        actor="alice",
        summary="Jira write approved by alice",
        details={"decision": "APPROVE", "tool_name": "createJiraIssue"},
    )

    persist_workflow_result(repository, claimed, completed(), events=events)

    done = events.list_history(kinds=[IncidentEventKind.INVESTIGATION_COMPLETED]).events[0]
    assert done.details["jira_key"] == "SAM1-25"


def test_pause_records_review_requested(session, events) -> None:
    repository, claimed = claimed_investigation(session)
    review = HumanReview(
        review_type=HumanReviewType.JIRA_WRITE,
        reason="Create the tracking issue.",
        draft={"tool_name": "createJiraIssue", "tool_args": {"summary": "Checkout down"}},
    )

    persist_workflow_result(
        repository,
        claimed,
        {"report": None, "human_review": review, "__interrupt__": [object()]},
        events=events,
    )

    [event] = events.list_history().events
    assert event.kind is IncidentEventKind.REVIEW_REQUESTED
    assert event.details == {"review_type": "JIRA_WRITE", "tool_name": "createJiraIssue"}


def test_failure_records_failed_with_error(session, events) -> None:
    repository, claimed = claimed_investigation(session)

    persist_workflow_result(repository, claimed, {"errors": ["No report."]}, events=events)

    [event] = events.list_history().events
    assert event.kind is IncidentEventKind.INVESTIGATION_FAILED
    assert event.details == {"error": "No report."}


def test_lost_lease_records_no_event(session, events) -> None:
    repository, claimed = claimed_investigation(session)
    stale = replace(claimed, lease_token="another-worker")

    with pytest.raises(LeaseLostError):
        persist_workflow_result(repository, stale, completed(), events=events)

    assert events.list_history().events == []
