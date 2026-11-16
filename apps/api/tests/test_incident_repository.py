from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.domain.incidents.models import (
    AlarmIncidentCreate,
    IncidentCreate,
    IncidentPriority,
    IncidentSource,
    IncidentStatus,
)
from incidentflow.domain.investigations.models import (
    InvestigationCreate,
    InvestigationLifecycle,
)
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import (
    DuplicateOpenIncidentError,
    IncidentRepository,
)
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM

ARN = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:if-checkout"


def alarm_data(external_id: str = ARN) -> AlarmIncidentCreate:
    return AlarmIncidentCreate(
        title="Checkout alarm in ALARM",
        description="Checkout API error rate crossed the alarm threshold.",
        priority=IncidentPriority.HIGH,
        service="checkout-api",
        external_id=external_id,
    )


def manual_data() -> IncidentCreate:
    return IncidentCreate(
        title="Manual incident",
        description="An operator reported a problem by hand.",
    )


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def repository(session: Session) -> IncidentRepository:
    return IncidentRepository(session)


def test_alarm_incident_keeps_source_service_and_external_id(
    repository: IncidentRepository,
) -> None:
    incident = repository.create_alarm_incident(alarm_data(external_id=ARN))

    assert incident.source is IncidentSource.CLOUDWATCH_ALARM
    assert incident.service == "checkout-api"
    assert incident.external_id == ARN


def test_manual_incident_defaults_to_manual_source(repository: IncidentRepository) -> None:
    incident = repository.create_incident(manual_data())

    assert incident.source is IncidentSource.MANUAL
    assert incident.service is None
    assert incident.external_id is None


def test_second_open_incident_for_same_alarm_is_rejected(
    repository: IncidentRepository,
) -> None:
    repository.create_alarm_incident(alarm_data(external_id=ARN))

    with pytest.raises(DuplicateOpenIncidentError):
        repository.create_alarm_incident(alarm_data(external_id=ARN))


def test_closed_alarm_incident_allows_a_new_one(repository: IncidentRepository) -> None:
    repository.create_alarm_incident(alarm_data(external_id=ARN))

    assert repository.close_open_alarm_incidents(["if-checkout"]) == 1
    assert (
        repository.create_alarm_incident(alarm_data(external_id=ARN)).status is IncidentStatus.OPEN
    )


def test_closing_ignores_manual_and_other_alarms(repository: IncidentRepository) -> None:
    manual = repository.create_incident(manual_data())
    other = repository.create_alarm_incident(
        alarm_data(external_id=ARN.replace("if-checkout", "if-checkout-prod"))
    )

    assert repository.close_open_alarm_incidents(["if-checkout"]) == 0
    assert repository.get_incident(manual.id).status is IncidentStatus.OPEN
    assert repository.get_incident(other.id).status is IncidentStatus.OPEN


def test_closing_an_incident_leaves_its_investigation_untouched(
    session: Session, repository: IncidentRepository
) -> None:
    incident = repository.create_alarm_incident(alarm_data(external_id=ARN))
    investigations = InvestigationRepository(session)
    investigation = investigations.create_investigation(
        InvestigationCreate(
            incident_id=incident.id,
            incident_request="Investigate the checkout alarm.",
            incident_business_status="OPEN",
        )
    )
    claimed = investigations.claim(investigation.id, lease_seconds=300)
    assert claimed is not None

    before = investigations.get_investigation(investigation.id)
    assert before is not None
    assert before.lifecycle is InvestigationLifecycle.RUNNING
    assert repository.close_open_alarm_incidents(["if-checkout"]) == 1
    after = investigations.get_investigation(investigation.id)
    assert after is not None
    assert after.lifecycle is InvestigationLifecycle.RUNNING


def _set_created_at(session: Session, incident_id, created_at: datetime) -> None:
    orm = session.get(IncidentORM, incident_id)
    orm.created_at = created_at
    session.commit()


def test_latest_alarm_incident_created_at_is_none_without_matches(
    repository: IncidentRepository,
) -> None:
    repository.create_incident(manual_data())
    repository.create_alarm_incident(
        alarm_data(external_id=ARN.replace("if-checkout", "if-checkout-prod"))
    )

    assert repository.latest_alarm_incident_created_at(["if-checkout"]) is None
    assert repository.latest_alarm_incident_created_at([]) is None


def test_latest_alarm_incident_created_at_returns_newest_in_any_status(
    session: Session, repository: IncidentRepository
) -> None:
    old = repository.create_alarm_incident(alarm_data(external_id=ARN))
    repository.close_open_alarm_incidents(["if-checkout"])
    new = repository.create_alarm_incident(alarm_data(external_id=ARN))
    other = repository.create_alarm_incident(
        alarm_data(external_id=ARN.replace("if-checkout", "if-orders"))
    )
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _set_created_at(session, old.id, now - timedelta(hours=2))
    _set_created_at(session, new.id, now - timedelta(minutes=5))
    _set_created_at(session, other.id, now)

    latest = repository.latest_alarm_incident_created_at(["if-checkout"])

    assert latest == now - timedelta(minutes=5)
    assert latest.tzinfo is not None
