"""Start a demo run: close the previous demo incidents, then replay the outages."""

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

import boto3
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from incidentflow.application.services.incident_ingestion_service import (
    IncidentIngestionService,
)
from incidentflow.core.config import Settings
from incidentflow.demo.scenarios import DEMO_ALARM_NAMES, SCENARIOS, Scenario
from incidentflow.demo.simulator import AlarmFired, DemoSimulator, alarm_arn
from incidentflow.domain.demo.models import DemoRunStarted
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)

logger = logging.getLogger(__name__)

# One local run at a time per process: overlapping runs would redefine the same alarms.
_LOCAL_RUN_LOCK = threading.Lock()


class DemoRunner(Protocol):
    def start(self, run_id: str) -> None: ...


class LambdaDemoRunner:
    """Run the simulator in the demo Lambda; EventBridge turns its alarms into incidents."""

    def __init__(self, lambda_client: Any, function_name: str) -> None:
        self._client = lambda_client
        self._function_name = function_name

    def start(self, run_id: str) -> None:
        self._client.invoke(
            FunctionName=self._function_name,
            InvocationType="Event",
            Payload=json.dumps({"run_id": run_id}),
        )


class ScenarioTagReader:
    """Return a scenario's alarm tags without calling AWS, as the simulator would set them."""

    def __init__(self, scenarios: dict[str, Scenario]) -> None:
        self._scenarios = scenarios

    def tags_for(self, alarm_arn: str) -> dict[str, str]:
        scenario = self._scenarios[alarm_arn.rsplit(":alarm:", 1)[1]]
        return {
            "incidentflow:title": scenario.title,
            "incidentflow:priority": scenario.priority.value,
            "incidentflow:service": scenario.service,
        }


def _boto_session(settings: Settings) -> Any:
    return boto3.Session(profile_name=settings.demo_aws_profile)


def _simulator(settings: Settings, aws_session: Any, on_alarm_fired: AlarmFired) -> Any:
    return DemoSimulator(
        aws_session.client("logs"),
        aws_session.client("cloudwatch"),
        aws_session.client("sts"),
        interval_seconds=settings.demo_interval_seconds,
        on_alarm_fired=on_alarm_fired,
    )


class LocalDemoRunner:
    """Run the simulator inside the API process and ingest each fired alarm directly.

    Locally there is no EventBridge rule, so each ALARM is turned into the same state-change
    event it would produce, and the same ingestion service creates the incident.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session],
        background: BackgroundTasks,
        *,
        aws_session_factory: Callable[[Settings], Any] = _boto_session,
        simulator_factory: Callable[[Any, AlarmFired], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._background = background
        self._aws_session_factory = aws_session_factory
        self._simulator_factory = simulator_factory or (
            lambda aws_session, fired: _simulator(settings, aws_session, fired)
        )

    def start(self, run_id: str) -> None:
        self._background.add_task(self.run, run_id)

    def run(self, run_id: str) -> None:
        if not _LOCAL_RUN_LOCK.acquire(blocking=False):
            logger.info("Local demo run %s skipped: another run is in progress.", run_id)
            return
        try:
            aws_session = self._aws_session_factory(self._settings)
            region = aws_session.region_name
            account = aws_session.client("sts").get_caller_identity()["Account"]
            tag_reader = ScenarioTagReader(self._scenarios_by_alarm())

            def on_alarm_fired(scenario: Scenario, _run_id: str) -> None:
                self._ingest(scenario, alarm_arn(region, account, scenario.alarm_name), tag_reader)

            self._simulator_factory(aws_session, on_alarm_fired).run(run_id)
        except Exception:
            logger.exception("Local demo run %s failed.", run_id)
        finally:
            _LOCAL_RUN_LOCK.release()

    @staticmethod
    def _scenarios_by_alarm() -> dict[str, Scenario]:
        return {scenario.alarm_name: scenario for scenario in SCENARIOS}

    def _ingest(self, scenario: Scenario, arn: str, tag_reader: ScenarioTagReader) -> None:
        event = {
            "detail-type": "CloudWatch Alarm State Change",
            "resources": [arn],
            "detail": {
                "alarmName": scenario.alarm_name,
                "state": {
                    "value": "ALARM",
                    "reason": f"Demo outage replay: {scenario.title}",
                },
                "configuration": {"description": scenario.description},
            },
        }
        with self._session_factory() as session:
            IncidentIngestionService(
                IncidentRepository(session), tag_reader, self._settings.ingest_alarm_prefix
            ).ingest_cloudwatch_alarm(event)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DemoService:
    def __init__(
        self,
        repository: IncidentRepository,
        runner: DemoRunner,
        auto_cooldown_seconds: int,
        now: Callable[[], datetime] = _utc_now,
        *,
        investigations: InvestigationRepository | None = None,
    ) -> None:
        self._repository = repository
        self._investigations = investigations
        self._runner = runner
        self._auto_cooldown = timedelta(seconds=auto_cooldown_seconds)
        self._now = now

    def start_run(self, only_if_idle: bool = False) -> DemoRunStarted:
        if only_if_idle and (self._recently_active() or self._under_investigation()):
            return DemoRunStarted(started=False)

        closed = self._repository.close_open_alarm_incidents(DEMO_ALARM_NAMES)
        run_id = uuid4().hex
        self._runner.start(run_id)
        return DemoRunStarted(started=True, run_id=run_id, closed_incidents=closed)

    def _recently_active(self) -> bool:
        latest = self._repository.latest_alarm_incident_created_at(DEMO_ALARM_NAMES)
        return latest is not None and self._now() - latest < self._auto_cooldown

    def _under_investigation(self) -> bool:
        if self._investigations is None:
            return False
        incident_ids = self._repository.list_open_alarm_incident_ids(DEMO_ALARM_NAMES)
        return self._investigations.has_active_investigation_among(incident_ids)
