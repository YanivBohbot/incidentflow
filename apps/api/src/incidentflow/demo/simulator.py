"""Replay the demo outages through real CloudWatch alarms.

For each run the simulator redefines the eight alarms with a per-run ``RunId`` dimension (so no
stale datapoint can keep them in ALARM), resets them to OK, then writes fresh logs and metrics for
one scenario at a time and forces that alarm into ALARM. The EventBridge rule turns each ALARM
state change into an incident.

boto3 docs check (PutMetricAlarm, read from the installed botocore service model, not online):
"When you update an existing alarm, its state is left unchanged, but the update completely
overwrites the previous configuration." So redefining an alarm does not by itself emit an ALARM
state change; only the explicit ``set_alarm_state(ALARM)`` below does. The alarm may re-evaluate
against the new RunId dimension afterwards, which has no data and so stays non-breaching
(``TreatMissingData="notBreaching"``).
"""

import json
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from incidentflow.demo.scenarios import METRIC_NAMESPACE, SCENARIOS, Scenario

AlarmFired = Callable[[Scenario, str], None]

PROJECT_TAG = {"Key": "project", "Value": "incidentflow"}
WINDOW = timedelta(minutes=10)
INCIDENT_MINUTES = 3
HOLD_MINUTES = 10


def alarm_arn(region: str, account: str, alarm_name: str) -> str:
    return f"arn:aws:cloudwatch:{region}:{account}:alarm:{alarm_name}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DemoSimulator:
    """Replay demo outages: put metrics and logs, then trip each scenario's alarm.

    Alarms are tagged explicitly because PutMetricAlarm only applies tags on creation.
    """

    def __init__(
        self,
        logs_client: Any,
        cloudwatch_client: Any,
        sts_client: Any,
        *,
        interval_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utc_now,
        on_alarm_fired: AlarmFired | None = None,
    ) -> None:
        self._logs = logs_client
        self._cloudwatch = cloudwatch_client
        self._sts = sts_client
        self._interval_seconds = interval_seconds
        self._sleep = sleep
        self._now = now
        self._on_alarm_fired = on_alarm_fired

    def run(self, run_id: str) -> None:
        """Fire every scenario in turn, one alarm per interval."""
        account = self._sts.get_caller_identity()["Account"]
        region = self._cloudwatch.meta.region_name
        for scenario in SCENARIOS:
            self._define_alarm(scenario, run_id)
            self._tag_alarm(scenario, alarm_arn(region, account, scenario.alarm_name))
        for scenario in SCENARIOS:
            self._set_state(scenario, "OK", "Demo run reset", run_id)
        for index, scenario in enumerate(SCENARIOS):
            self._ensure_log_stream(scenario, run_id)
            self._put_logs(scenario, run_id)
            self._put_metrics(scenario, run_id)
            self._set_state(scenario, "ALARM", f"Demo outage replay: {scenario.title}", run_id)
            if self._on_alarm_fired is not None:
                self._on_alarm_fired(scenario, run_id)
            if index < len(SCENARIOS) - 1:
                self._sleep(self._interval_seconds)

    def _define_alarm(self, scenario: Scenario, run_id: str) -> None:
        self._cloudwatch.put_metric_alarm(
            AlarmName=scenario.alarm_name,
            AlarmDescription=scenario.description,
            Namespace=METRIC_NAMESPACE,
            MetricName=scenario.metric,
            Dimensions=_dimensions(scenario, run_id),
            Statistic="Maximum",
            Period=60,
            EvaluationPeriods=3,
            Threshold=scenario.threshold,
            ComparisonOperator="GreaterThanThreshold",
            TreatMissingData="notBreaching",
            Tags=_alarm_tags(scenario),
        )

    def _tag_alarm(self, scenario: Scenario, arn: str) -> None:
        self._cloudwatch.tag_resource(ResourceARN=arn, Tags=_alarm_tags(scenario))

    def _set_state(self, scenario: Scenario, state: str, reason: str, run_id: str) -> None:
        self._cloudwatch.set_alarm_state(
            AlarmName=scenario.alarm_name,
            StateValue=state,
            StateReason=reason,
            StateReasonData=json.dumps({"run_id": run_id}),
        )

    def _ensure_log_stream(self, scenario: Scenario, run_id: str) -> None:
        already_exists = self._logs.exceptions.ResourceAlreadyExistsException
        try:
            self._logs.create_log_group(
                logGroupName=scenario.log_group, tags={"project": "incidentflow"}
            )
        except already_exists:
            pass
        self._logs.put_retention_policy(logGroupName=scenario.log_group, retentionInDays=1)
        try:
            self._logs.create_log_stream(
                logGroupName=scenario.log_group, logStreamName=_stream_name(run_id)
            )
        except already_exists:
            pass

    def _put_logs(self, scenario: Scenario, run_id: str) -> None:
        now = self._now()
        incident_start = now - timedelta(minutes=INCIDENT_MINUTES)
        events, moment = [], now - WINDOW + timedelta(seconds=30)
        while moment <= now:
            if moment < incident_start:
                message = scenario.healthy_line.format(ms=random.randint(80, 200))
            else:
                message = random.choice(scenario.incident_lines)
            events.append({"timestamp": int(moment.timestamp() * 1000), "message": message})
            moment += timedelta(seconds=30)
        events[-1]["message"] = scenario.incident_lines[0]
        events.sort(key=lambda event: event["timestamp"])
        self._logs.put_log_events(
            logGroupName=scenario.log_group,
            logStreamName=_stream_name(run_id),
            logEvents=events,
        )

    def _put_metrics(self, scenario: Scenario, run_id: str) -> None:
        now = self._now().replace(second=0, microsecond=0)
        points = []
        for minutes_ago in range(9, -HOLD_MINUTES - 1, -1):
            incident = minutes_ago < INCIDENT_MINUTES
            low, high = scenario.incident if incident else scenario.baseline
            points.append(
                {
                    "MetricName": scenario.metric,
                    "Dimensions": _dimensions(scenario, run_id),
                    "Timestamp": now - timedelta(minutes=minutes_ago),
                    "Value": random.randint(low, high),
                    "Unit": scenario.unit,
                }
            )
        self._cloudwatch.put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=points)


def _alarm_tags(scenario: Scenario) -> list[dict[str, str]]:
    return [
        {"Key": "incidentflow:title", "Value": scenario.title},
        {"Key": "incidentflow:priority", "Value": scenario.priority.value},
        {"Key": "incidentflow:service", "Value": scenario.service},
        PROJECT_TAG,
    ]


def _dimensions(scenario: Scenario, run_id: str) -> list[dict[str, str]]:
    return [
        {"Name": "Service", "Value": scenario.service},
        {"Name": "RunId", "Value": run_id},
    ]


def _stream_name(run_id: str) -> str:
    return f"run-{run_id}"
