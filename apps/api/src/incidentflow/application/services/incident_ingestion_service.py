"""Turns CloudWatch alarm events into incidents, one open incident per alarm."""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.incidents.models import (
    AlarmIncidentCreate,
    Incident,
    IncidentPriority,
)
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_repository import (
    DuplicateOpenIncidentError,
    IncidentRepository,
)

logger = logging.getLogger(__name__)

ALARM_DETAIL_TYPE = "CloudWatch Alarm State Change"
TITLE_TAG = "incidentflow:title"
PRIORITY_TAG = "incidentflow:priority"
SERVICE_TAG = "incidentflow:service"
MIN_TITLE = 5
MAX_TITLE = 200
MIN_DESCRIPTION = 10
MAX_DESCRIPTION = 5000
MAX_SERVICE = 200


class AlarmTagReader(Protocol):
    def tags_for(self, alarm_arn: str) -> dict[str, str]: ...


class CloudWatchAlarmTagReader:
    """Read the incident title, priority, and service from alarm tags."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def tags_for(self, alarm_arn: str) -> dict[str, str]:
        response = self._client.list_tags_for_resource(ResourceARN=alarm_arn)
        return {tag["Key"]: tag["Value"] for tag in response.get("Tags", [])}


class IngestionOutcome(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


@dataclass(frozen=True)
class IngestionResult:
    """Whether an alarm event created an incident, and which one."""

    outcome: IngestionOutcome
    incident: Incident | None


class IncidentIngestionService:
    """Create incidents from alarm state changes."""

    def __init__(
        self,
        repository: IncidentRepository,
        tag_reader: AlarmTagReader,
        alarm_prefix: str,
        *,
        events: IncidentEventRepository | None = None,
    ) -> None:
        self._repository = repository
        self._events = events
        self._tag_reader = tag_reader
        self._alarm_prefix = alarm_prefix

    def ingest_cloudwatch_alarm(self, event: dict[str, Any]) -> IngestionResult:
        """Create an incident when a prefixed alarm enters ALARM; ignore other events."""
        detail = event.get("detail") or {}
        name = str(detail.get("alarmName") or "")
        state = detail.get("state") or {}
        if event.get("detail-type") != ALARM_DETAIL_TYPE or state.get("value") != "ALARM":
            return self._finish(name, IngestionResult(IngestionOutcome.IGNORED, None))

        arn = event["resources"][0]
        tags = self._tag_reader.tags_for(arn)
        data = AlarmIncidentCreate(
            title=self._title(tags, name),
            description=self._description(detail, name),
            priority=self._priority(tags),
            service=(tags.get(SERVICE_TAG) or self._strip_prefix(name))[:MAX_SERVICE],
            external_id=arn,
        )
        try:
            incident = self._repository.create_alarm_incident(data)
        except DuplicateOpenIncidentError:
            return self._finish(name, IngestionResult(IngestionOutcome.DUPLICATE, None))
        if self._events is not None:
            self._events.record(
                IncidentEventKind.INCIDENT_CREATED,
                incident_id=incident.id,
                summary=f"CloudWatch alarm {name} raised the incident",
                details={"source": "CLOUDWATCH_ALARM", "alarm": name},
            )
        return self._finish(name, IngestionResult(IngestionOutcome.CREATED, incident))

    def _finish(self, name: str, result: IngestionResult) -> IngestionResult:
        logger.info(
            "ingested alarm=%s outcome=%s incident=%s",
            name,
            result.outcome.value,
            result.incident.id if result.incident else None,
        )
        return result

    def _strip_prefix(self, name: str) -> str:
        if self._alarm_prefix and name.startswith(self._alarm_prefix):
            return name[len(self._alarm_prefix) :]
        return name

    @staticmethod
    def _title(tags: dict[str, str], name: str) -> str:
        title = (tags.get(TITLE_TAG) or "").strip()
        if len(title) < MIN_TITLE:
            title = f"{name} in ALARM"
        return title[:MAX_TITLE]

    @staticmethod
    def _description(detail: dict[str, Any], name: str) -> str:
        configuration = detail.get("configuration") or {}
        state = detail.get("state") or {}
        text = str(configuration.get("description") or state.get("reason") or "").strip()
        if len(text) < MIN_DESCRIPTION:
            text = f"{text} (CloudWatch alarm {name})".strip()
        return text[:MAX_DESCRIPTION]

    @staticmethod
    def _priority(tags: dict[str, str]) -> IncidentPriority:
        try:
            return IncidentPriority((tags.get(PRIORITY_TAG) or "").strip().upper())
        except ValueError:
            return IncidentPriority.MEDIUM
