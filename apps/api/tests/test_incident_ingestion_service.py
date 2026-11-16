from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.application.services.incident_ingestion_service import (
    CloudWatchAlarmTagReader,
    IncidentIngestionService,
    IngestionOutcome,
)
from incidentflow.domain.incidents.models import IncidentPriority
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import IncidentRepository


class FakeTagReader:
    def __init__(self, tags: dict[str, str]) -> None:
        self.tags = tags

    def tags_for(self, alarm_arn: str) -> dict[str, str]:
        return self.tags


def alarm_event(
    name: str,
    tags: dict[str, str] | None = None,
    description: str | None = "checkout-api returns 503 for most requests",
    reason: str = "Threshold Crossed: 1 datapoint [5.0] was greater than 1.0",
    state: str = "ALARM",
    detail_type: str = "CloudWatch Alarm State Change",
) -> dict[str, Any]:
    configuration: dict[str, Any] = {}
    if description is not None:
        configuration["description"] = description
    event = {
        "detail-type": detail_type,
        "resources": [f"arn:aws:cloudwatch:us-east-1:123456789012:alarm:{name}"],
        "detail": {
            "alarmName": name,
            "state": {"value": state, "reason": reason},
            "configuration": configuration,
        },
    }
    event["_tags"] = tags or {}
    return event


@pytest.fixture
def repository() -> Iterator[IncidentRepository]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield IncidentRepository(session)


def make_service(repository: IncidentRepository, tags: dict[str, str]) -> IncidentIngestionService:
    return IncidentIngestionService(repository, FakeTagReader(tags), alarm_prefix="if-")


def ingest(repository: IncidentRepository, event: dict[str, Any]):
    tags = event.pop("_tags")
    return make_service(repository, tags).ingest_cloudwatch_alarm(event)


def test_alarm_event_creates_incident_from_tags(repository: IncidentRepository) -> None:
    result = ingest(
        repository,
        alarm_event(
            "if-checkout",
            tags={
                "incidentflow:title": "Checkout down",
                "incidentflow:priority": "critical",
                "incidentflow:service": "checkout-api",
            },
        ),
    )

    assert result.outcome is IngestionOutcome.CREATED
    assert result.incident is not None
    assert (result.incident.title, result.incident.priority, result.incident.service) == (
        "Checkout down",
        IncidentPriority.CRITICAL,
        "checkout-api",
    )
    assert result.incident.external_id.endswith(":alarm:if-checkout")


def test_untagged_alarm_falls_back_to_name_and_medium(repository: IncidentRepository) -> None:
    result = ingest(repository, alarm_event("if-billing", description=None))

    assert result.incident is not None
    assert result.incident.title == "if-billing in ALARM"
    assert result.incident.priority is IncidentPriority.MEDIUM
    assert result.incident.service == "billing"
    assert result.incident.description.startswith("Threshold Crossed")


def test_short_and_long_texts_are_fitted(repository: IncidentRepository) -> None:
    short = ingest(repository, alarm_event("if-a", description="x", reason="r"))
    long = ingest(
        repository,
        alarm_event("if-b", tags={"incidentflow:title": "t" * 300}, description="d" * 6000),
    )

    assert short.incident is not None and len(short.incident.description) >= 10
    assert long.incident is not None
    assert len(long.incident.title) == 200
    assert len(long.incident.description) == 5000


def test_too_short_title_tag_falls_back_to_alarm_name(repository: IncidentRepository) -> None:
    result = ingest(repository, alarm_event("if-a", tags={"incidentflow:title": "ab"}))

    assert result.incident is not None
    assert result.incident.title == "if-a in ALARM"


def test_non_alarm_state_is_ignored(repository: IncidentRepository) -> None:
    result = ingest(repository, alarm_event("if-a", state="OK"))

    assert result.outcome is IngestionOutcome.IGNORED
    assert result.incident is None
    assert repository.list_incidents() == []


def test_other_detail_type_is_ignored(repository: IncidentRepository) -> None:
    result = ingest(repository, alarm_event("if-a", detail_type="Something Else"))

    assert result.outcome is IngestionOutcome.IGNORED
    assert repository.list_incidents() == []


def test_same_event_twice_is_a_duplicate(repository: IncidentRepository) -> None:
    service = make_service(repository, {})
    event = alarm_event("if-a")
    event.pop("_tags")

    service.ingest_cloudwatch_alarm(event)
    second = service.ingest_cloudwatch_alarm(event)

    assert second.outcome is IngestionOutcome.DUPLICATE
    assert second.incident is None
    assert len(repository.list_incidents()) == 1


def test_unknown_priority_tag_falls_back_to_medium(repository: IncidentRepository) -> None:
    result = ingest(repository, alarm_event("if-a", tags={"incidentflow:priority": "urgent"}))

    assert result.incident is not None
    assert result.incident.priority is IncidentPriority.MEDIUM


def test_cloudwatch_tag_reader_converts_tag_list_to_dict() -> None:
    class FakeClient:
        def list_tags_for_resource(self, ResourceARN: str) -> dict[str, Any]:
            assert ResourceARN == "arn:x"
            return {"Tags": [{"Key": "a", "Value": "1"}, {"Key": "b", "Value": "2"}]}

    assert CloudWatchAlarmTagReader(FakeClient()).tags_for("arn:x") == {"a": "1", "b": "2"}
