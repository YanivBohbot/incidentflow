from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.incidents.models import (
    AlarmIncidentCreate,
    IncidentCreate,
    IncidentPriority,
)
from incidentflow.domain.investigations.models import InvestigationCreate
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)

T0 = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def events(session: Session) -> IncidentEventRepository:
    return IncidentEventRepository(session)


def make_incident(session: Session, title: str = "Checkout down"):
    return IncidentRepository(session).create_incident(
        IncidentCreate(title=title, description="checkout-api returns HTTP 503.")
    )


def record(events, kind, incident, minutes, **kwargs):
    return events.record(
        kind,
        incident_id=incident.id if incident else None,
        summary=f"{kind.value} at {minutes}",
        occurred_at=T0 + timedelta(minutes=minutes),
        **kwargs,
    )


def test_record_and_list_history_newest_first(session, events) -> None:
    incident = make_incident(session)
    record(events, IncidentEventKind.INCIDENT_CREATED, incident, 0, actor="system")
    record(events, IncidentEventKind.INCIDENT_RESOLVED, incident, 5, actor="alice")

    page = events.list_history()

    assert [item.kind for item in page.events] == [
        IncidentEventKind.INCIDENT_RESOLVED,
        IncidentEventKind.INCIDENT_CREATED,
    ]
    assert page.events[0].actor == "alice"
    assert page.events[0].occurred_at == T0 + timedelta(minutes=5)
    assert page.next_before is None


def test_history_filters_by_incident_and_kinds(session, events) -> None:
    checkout, login = make_incident(session), make_incident(session, "Login failures")
    record(events, IncidentEventKind.INCIDENT_CREATED, checkout, 0)
    record(events, IncidentEventKind.INCIDENT_RESOLVED, checkout, 1)
    record(events, IncidentEventKind.INCIDENT_RESOLVED, login, 2)

    by_incident = events.list_history(incident_id=checkout.id)
    by_kind = events.list_history(kinds=[IncidentEventKind.INCIDENT_RESOLVED])

    assert {item.incident_id for item in by_incident.events} == {checkout.id}
    assert len(by_incident.events) == 2
    assert {item.kind for item in by_kind.events} == {IncidentEventKind.INCIDENT_RESOLVED}
    assert len(by_kind.events) == 2


def test_before_cursor_pages_without_gaps_or_repeats(session, events) -> None:
    incident = make_incident(session)
    for minutes in (0, 1, 1, 1, 2):
        record(events, IncidentEventKind.INCIDENT_CREATED, incident, minutes)

    seen, before = [], None
    while True:
        page = events.list_history(before=before, limit=2)
        seen += [item.id for item in page.events]
        if page.next_before is None:
            break
        before = page.next_before

    assert len(seen) == 5
    assert len(set(seen)) == 5


def test_incident_journal_is_oldest_first(session, events) -> None:
    incident = make_incident(session)
    record(events, IncidentEventKind.INCIDENT_RESOLVED, incident, 9)
    record(events, IncidentEventKind.INCIDENT_CREATED, incident, 0)

    journal = events.list_for_incident(incident.id)

    assert [item.kind for item in journal] == [
        IncidentEventKind.INCIDENT_CREATED,
        IncidentEventKind.INCIDENT_RESOLVED,
    ]
    assert events.has_events_for_incident(incident.id) is True


def test_history_rows_carry_the_incident_title(session, events) -> None:
    incident = make_incident(session)
    record(events, IncidentEventKind.INCIDENT_CREATED, incident, 0)
    record(events, IncidentEventKind.DEMO_RUN_STARTED, None, 1, details={"run_id": "r1"})

    page = events.list_history()

    assert page.events[0].incident_title is None
    assert page.events[0].details == {"run_id": "r1"}
    assert page.events[1].incident_title == "Checkout down"


def test_deleting_an_incident_deletes_its_events(session, events) -> None:
    incident = make_incident(session)
    record(events, IncidentEventKind.INCIDENT_CREATED, incident, 0)

    assert IncidentRepository(session).delete_incident(incident.id) is True

    assert events.list_history().events == []


def test_history_filters_by_category_service_or_title(session, events) -> None:
    repository = IncidentRepository(session)
    first = repository.create_alarm_incident(
        AlarmIncidentCreate(
            title="Checkout down",
            description="First demo run.",
            priority=IncidentPriority.CRITICAL,
            service="checkout-api",
            external_id="arn:aws:cloudwatch:us-east-1:1:alarm:a",
        )
    )
    repository.close_open_alarm_incidents(["a"])
    second = repository.create_alarm_incident(
        AlarmIncidentCreate(
            title="Checkout down again",
            description="Second demo run.",
            priority=IncidentPriority.CRITICAL,
            service="checkout-api",
            external_id="arn:aws:cloudwatch:us-east-1:1:alarm:a",
        )
    )
    manual = make_incident(session, "Printer on fire")
    for minutes, incident in enumerate((first, second, manual)):
        record(events, IncidentEventKind.INCIDENT_CREATED, incident, minutes)

    by_service = events.list_history(category="checkout-api")
    by_title = events.list_history(category="Printer on fire")

    assert {item.incident_id for item in by_service.events} == {first.id, second.id}
    assert {item.incident_service for item in by_service.events} == {"checkout-api"}
    assert [item.incident_id for item in by_title.events] == [manual.id]
    assert by_title.events[0].incident_service is None


def test_history_can_hide_incidents_closed_without_investigation(session, events) -> None:
    repository = IncidentRepository(session)
    untouched = repository.create_alarm_incident(
        AlarmIncidentCreate(
            title="Checkout down",
            description="Closed by the next demo run.",
            priority=IncidentPriority.CRITICAL,
            service="checkout-api",
            external_id="arn:aws:cloudwatch:us-east-1:1:alarm:b",
        )
    )
    repository.close_open_alarm_incidents(["b"])
    investigated = make_incident(session, "Login failures")
    InvestigationRepository(session).create_investigation(
        InvestigationCreate(
            incident_id=investigated.id,
            incident_request="Investigate login.",
            incident_business_status="OPEN",
        )
    )
    still_open = make_incident(session, "Printer on fire")
    for minutes, incident in enumerate((untouched, investigated, still_open)):
        record(events, IncidentEventKind.INCIDENT_CREATED, incident, minutes)
    record(events, IncidentEventKind.DEMO_RUN_STARTED, None, 5)

    shown = events.list_history(hide_untouched=True)
    everything = events.list_history()

    assert untouched.id not in {item.incident_id for item in shown.events}
    assert {investigated.id, still_open.id, None} <= {item.incident_id for item in shown.events}
    assert len(everything.events) == 4
