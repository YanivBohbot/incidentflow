from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.application.jobs.queue import InMemoryJobQueue
from incidentflow.application.services.demo_service import DemoService
from incidentflow.application.services.incident_ingestion_service import (
    IncidentIngestionService,
)
from incidentflow.application.services.incident_lesson_service import IncidentLessonService
from incidentflow.application.services.incident_service import IncidentService
from incidentflow.application.services.investigation_service import (
    InvestigationAlreadyActiveError,
    InvestigationService,
)
from incidentflow.demo.scenarios import SCENARIOS
from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewDecision,
    HumanReviewType,
)
from incidentflow.domain.incidents.models import (
    AlarmIncidentCreate,
    IncidentCreate,
    IncidentPriority,
)
from incidentflow.domain.investigations.models import (
    InvestigationCreate,
    InvestigationLifecycle,
    InvestigationStart,
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
from incidentflow.infrastructure.database.models import InvestigationORM

ALARM_ARN = f"arn:aws:cloudwatch:us-east-1:123456789012:alarm:{SCENARIOS[0].alarm_name}"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def events(session: Session) -> IncidentEventRepository:
    return IncidentEventRepository(session)


def kinds(events: IncidentEventRepository) -> list[IncidentEventKind]:
    return [item.kind for item in reversed(events.list_history().events)]


def manual_incident(session: Session):
    return IncidentRepository(session).create_incident(
        IncidentCreate(title="Checkout down", description="checkout-api returns HTTP 503.")
    )


def investigation_service(session, events) -> InvestigationService:
    return InvestigationService(
        InvestigationRepository(session),
        IncidentRepository(session),
        InMemoryJobQueue(),
        object(),
        events=events,
    )


class FakeTagReader:
    def tags_for(self, alarm_arn: str) -> dict[str, str]:
        return {"incidentflow:title": "Checkout down", "incidentflow:priority": "CRITICAL"}


def alarm_event() -> dict:
    return {
        "detail-type": "CloudWatch Alarm State Change",
        "resources": [ALARM_ARN],
        "detail": {"alarmName": SCENARIOS[0].alarm_name, "state": {"value": "ALARM"}},
    }


class FakeRunner:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def start(self, run_id: str) -> None:
        self.run_ids.append(run_id)


def test_manual_incident_records_created_event_with_actor(session, events) -> None:
    service = IncidentService(IncidentRepository(session), events=events)

    incident = service.create_incident(
        IncidentCreate(title="Checkout down", description="checkout-api returns HTTP 503."),
        actor="alice",
    )

    [created] = events.list_for_incident(incident.id)
    assert created.kind is IncidentEventKind.INCIDENT_CREATED
    assert created.actor == "alice"
    assert created.details["source"] == "MANUAL"


def test_alarm_ingestion_records_created_event_once(session, events) -> None:
    service = IncidentIngestionService(
        IncidentRepository(session), FakeTagReader(), "if-", events=events
    )

    service.ingest_cloudwatch_alarm(alarm_event())
    service.ingest_cloudwatch_alarm(alarm_event())

    page = events.list_history()
    assert [item.kind for item in page.events] == [IncidentEventKind.INCIDENT_CREATED]
    assert page.events[0].actor == "system"
    assert page.events[0].details["source"] == "CLOUDWATCH_ALARM"


def test_start_records_event_and_conflict_records_none(session, events) -> None:
    incident = manual_incident(session)
    service = investigation_service(session, events)
    data = InvestigationStart(incident_id=incident.id, incident_request="Investigate checkout.")

    investigation = service.start_investigation(data, actor="alice")
    with pytest.raises(InvestigationAlreadyActiveError):
        service.start_investigation(data, actor="alice")

    [started] = events.list_for_incident(incident.id)
    assert started.kind is IncidentEventKind.INVESTIGATION_STARTED
    assert started.investigation_id == investigation.id
    assert started.actor == "alice"


def test_resolve_records_event_once(session, events) -> None:
    incident = manual_incident(session)
    service = IncidentService(IncidentRepository(session), events=events)

    service.resolve_incident(incident.id, actor="alice")
    service.resolve_incident(incident.id, actor="alice")

    assert kinds(events) == [IncidentEventKind.INCIDENT_RESOLVED]
    assert events.list_history().events[0].actor == "alice"


def test_review_decision_records_actor_and_decision(session, events) -> None:
    incident = manual_incident(session)
    investigation = InvestigationRepository(session).create_investigation(
        InvestigationCreate(
            incident_id=incident.id,
            incident_request="Investigate checkout.",
            incident_business_status="OPEN",
        )
    )
    orm = session.get(InvestigationORM, investigation.id)
    orm.lifecycle = InvestigationLifecycle.AWAITING_HUMAN_REVIEW
    orm.pending_human_review_payload = HumanReview(
        review_type=HumanReviewType.JIRA_WRITE,
        reason="Create the tracking issue.",
        draft={"tool_name": "createJiraIssue", "tool_args": {"summary": "Checkout down"}},
    ).model_dump(mode="json")
    session.commit()

    investigation_service(session, events).request_human_review_resume(
        investigation.id,
        HumanReviewDecision(decision="APPROVE", actor="alice", reason="Looks right"),
    )

    [decided] = events.list_for_incident(incident.id)
    assert decided.kind is IncidentEventKind.REVIEW_DECIDED
    assert decided.actor == "alice"
    assert decided.details == {
        "decision": "APPROVE",
        "reason": "Looks right",
        "review_type": "JIRA_WRITE",
        "tool_name": "createJiraIssue",
    }


def test_demo_run_records_closed_and_started(session, events) -> None:
    repository = IncidentRepository(session)
    previous = repository.create_alarm_incident(
        AlarmIncidentCreate(
            title="Checkout down",
            description="Previous demo run.",
            priority=IncidentPriority.CRITICAL,
            service="checkout-api",
            external_id=ALARM_ARN,
        )
    )
    runner = FakeRunner()
    service = DemoService(repository, runner, 600, lambda: datetime.now(UTC), events=events)

    started = service.start_run(actor="alice")

    [closed] = events.list_for_incident(previous.id)
    assert closed.kind is IncidentEventKind.INCIDENT_CLOSED
    assert closed.details["run_id"] == started.run_id
    run = events.list_history(kinds=[IncidentEventKind.DEMO_RUN_STARTED]).events[0]
    assert run.incident_id is None
    assert run.actor == "alice"
    assert run.details == {"run_id": started.run_id, "closed": 1}


def test_refused_demo_run_records_nothing(session, events) -> None:
    repository = IncidentRepository(session)
    repository.create_alarm_incident(
        AlarmIncidentCreate(
            title="Checkout down",
            description="A run is in progress.",
            priority=IncidentPriority.CRITICAL,
            service="checkout-api",
            external_id=ALARM_ARN,
        )
    )
    service = DemoService(
        repository,
        FakeRunner(),
        600,
        lambda: datetime.now(UTC),
        events=events,
        run_in_progress_seconds=60,
    )

    assert service.start_run(actor="alice").started is False

    assert events.list_history().events == []


class FakeIndexer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def index_confirmed_incident_lesson(self, lesson) -> str:
        if self.fail:
            raise RuntimeError("Pinecone unavailable")
        return f"lesson-{uuid4()}"


@pytest.mark.parametrize("fail", [False, True])
def test_confirmed_lesson_records_event_and_failed_index_does_not(session, events, fail) -> None:
    incident = manual_incident(session)
    investigation = InvestigationRepository(session).create_investigation(
        InvestigationCreate(
            incident_id=incident.id,
            incident_request="Investigate checkout.",
            incident_business_status="OPEN",
        )
    )
    session.get(InvestigationORM, investigation.id).lifecycle = InvestigationLifecycle.COMPLETED
    session.commit()
    service = IncidentLessonService(
        IncidentLessonRepository(session), FakeIndexer(fail), events=events
    )

    service.confirm_and_index(
        IncidentLessonConfirmation(
            investigation_id=investigation.id,
            service="checkout-api",
            environment="production",
            confirmed_root_cause="Pool exhausted.",
            validated_resolution="Raised the pool size.",
        ),
        actor="alice",
    )

    saved = events.list_for_incident(incident.id)
    if fail:
        assert saved == []
    else:
        assert [item.kind for item in saved] == [IncidentEventKind.LESSON_SAVED]
        assert saved[0].investigation_id == investigation.id
        assert saved[0].actor == "alice"
