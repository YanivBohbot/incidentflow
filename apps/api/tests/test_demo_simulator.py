import json
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.stub import Stubber

from incidentflow.demo.scenarios import METRIC_NAMESPACE, SCENARIOS
from incidentflow.demo.simulator import DemoSimulator, alarm_arn

NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
CLIENT_ARGS = {
    "region_name": "us-east-1",
    "aws_access_key_id": "testing",
    "aws_secret_access_key": "testing",
}


class Rig:
    """Real boto3 clients under Stubber; every call is recorded as (operation, params)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.sleeps: list[float] = []
        self.fired: list[tuple[str, str]] = []
        self.logs = boto3.client("logs", **CLIENT_ARGS)
        self.cloudwatch = boto3.client("cloudwatch", **CLIENT_ARGS)
        self.sts = boto3.client("sts", **CLIENT_ARGS)
        for client in (self.logs, self.cloudwatch, self.sts):
            client.meta.events.register(
                "before-parameter-build.*.*", lambda params, model, **_: self._record(model, params)
            )
        self.logs_stub = Stubber(self.logs)
        self.cloudwatch_stub = Stubber(self.cloudwatch)
        self.sts_stub = Stubber(self.sts)

    def _record(self, model, params) -> None:
        self.calls.append((model.name, dict(params)))

    def expect_all(self, *, already_exists: bool = False) -> None:
        count = len(SCENARIOS)
        for _ in range(count):
            for operation in ("create_log_group", "put_retention_policy", "create_log_stream"):
                if already_exists and operation != "put_retention_policy":
                    self.logs_stub.add_client_error(operation, "ResourceAlreadyExistsException")
                else:
                    self.logs_stub.add_response(operation, {})
            self.logs_stub.add_response("put_log_events", {})
        self.sts_stub.add_response(
            "get_caller_identity",
            {"UserId": "u", "Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/u"},
        )
        for _ in range(count):
            self.cloudwatch_stub.add_response("put_metric_alarm", {})
            self.cloudwatch_stub.add_response("tag_resource", {})
        for _ in range(count):
            self.cloudwatch_stub.add_response("set_alarm_state", {})
        for _ in range(count):
            self.cloudwatch_stub.add_response("put_metric_data", {})
            self.cloudwatch_stub.add_response("set_alarm_state", {})

    def simulator(self, *, with_hook: bool = False) -> DemoSimulator:
        return DemoSimulator(
            self.logs,
            self.cloudwatch,
            self.sts,
            interval_seconds=45,
            sleep=self.sleeps.append,
            now=lambda: NOW,
            on_alarm_fired=(lambda s, r: self.fired.append((s.alarm_name, r)))
            if with_hook
            else None,
        )

    def named(self, operation: str) -> list[dict]:
        return [params for name, params in self.calls if name == operation]


@pytest.fixture
def rig():
    rig = Rig()
    rig.expect_all()
    rig.logs_stub.activate()
    rig.cloudwatch_stub.activate()
    rig.sts_stub.activate()
    return rig


def test_run_redefines_alarms_with_run_dimension_then_resets_them(rig):
    rig.simulator().run("r1")

    alarms = rig.named("PutMetricAlarm")
    assert [a["AlarmName"] for a in alarms] == [s.alarm_name for s in SCENARIOS]
    for alarm, scenario in zip(alarms, SCENARIOS, strict=True):
        assert {"Name": "Service", "Value": scenario.service} in alarm["Dimensions"]
        assert {"Name": "RunId", "Value": "r1"} in alarm["Dimensions"]
        assert alarm["TreatMissingData"] == "notBreaching"
        assert alarm["AlarmDescription"] == scenario.description
        assert alarm["Namespace"] == METRIC_NAMESPACE
        assert alarm["MetricName"] == scenario.metric
        assert alarm["Threshold"] == scenario.threshold
        assert alarm["Statistic"] == "Maximum"
        assert alarm["Period"] == 60
        assert alarm["EvaluationPeriods"] == 3
        assert alarm["ComparisonOperator"] == "GreaterThanThreshold"
        assert alarm["Tags"] == [
            {"Key": "incidentflow:title", "Value": scenario.title},
            {"Key": "incidentflow:priority", "Value": scenario.priority.value},
            {"Key": "incidentflow:service", "Value": scenario.service},
            {"Key": "project", "Value": "incidentflow"},
        ]

    resets = rig.named("SetAlarmState")[:8]
    assert [p["StateValue"] for p in resets] == ["OK"] * 8
    assert [p["AlarmName"] for p in resets] == [s.alarm_name for s in SCENARIOS]
    ordered = [name for name, _ in rig.calls if name in ("PutMetricAlarm", "SetAlarmState")]
    assert ordered[:16] == ["PutMetricAlarm"] * 8 + ["SetAlarmState"] * 8


def test_run_tags_every_alarm_after_defining_it_because_updates_ignore_tags(rig):
    rig.simulator().run("r1")

    tagged = rig.named("TagResource")
    assert len(tagged) == len(SCENARIOS)
    for call, scenario in zip(tagged, SCENARIOS, strict=True):
        assert call["ResourceARN"] == alarm_arn("us-east-1", "123456789012", scenario.alarm_name)
        assert call["Tags"] == [
            {"Key": "incidentflow:title", "Value": scenario.title},
            {"Key": "incidentflow:priority", "Value": scenario.priority.value},
            {"Key": "incidentflow:service", "Value": scenario.service},
            {"Key": "project", "Value": "incidentflow"},
        ]
    assert len(rig.named("GetCallerIdentity")) == 1
    ordered = [n for n, _ in rig.calls if n in ("PutMetricAlarm", "TagResource")]
    assert ordered[:16] == ["PutMetricAlarm", "TagResource"] * 8


def test_run_fires_alarms_in_scenario_order_with_interval(rig):
    rig.simulator().run("r1")

    firing = [p for p in rig.named("SetAlarmState") if p["StateValue"] == "ALARM"]
    assert [p["AlarmName"] for p in firing] == [s.alarm_name for s in SCENARIOS]
    assert all(p["StateReasonData"] == '{"run_id": "r1"}' for p in firing)
    assert all(p["StateReason"] for p in firing)
    assert rig.sleeps == [45] * 7


def test_run_writes_fresh_logs_and_metrics_before_each_alarm(rig):
    rig.simulator().run("r1")

    floor_ms = int((NOW - timedelta(minutes=10)).timestamp() * 1000)
    ceiling_ms = int(NOW.timestamp() * 1000)
    uploads = rig.named("PutLogEvents")
    assert [u["logGroupName"] for u in uploads] == [s.log_group for s in SCENARIOS]
    for upload in uploads:
        stamps = [e["timestamp"] for e in upload["logEvents"]]
        assert upload["logStreamName"] == "run-r1"
        assert stamps == sorted(stamps)
        assert all(floor_ms <= stamp <= ceiling_ms for stamp in stamps)
    for upload, scenario in zip(uploads, SCENARIOS, strict=True):
        messages = [e["message"] for e in upload["logEvents"]]
        assert any(m in scenario.incident_lines for m in messages)
        assert not any("{ms}" in m for m in messages)

    batches = rig.named("PutMetricData")
    assert len(batches) == 8
    for batch, scenario in zip(batches, SCENARIOS, strict=True):
        assert batch["Namespace"] == METRIC_NAMESPACE
        for point in batch["MetricData"]:
            assert point["MetricName"] == scenario.metric
            assert point["Unit"] == scenario.unit
            assert {"Name": "RunId", "Value": "r1"} in point["Dimensions"]
            assert {"Name": "Service", "Value": scenario.service} in point["Dimensions"]
            assert NOW - timedelta(minutes=10) <= point["Timestamp"] <= NOW + timedelta(minutes=10)
        assert max(p["Value"] for p in batch["MetricData"]) > scenario.threshold or (
            scenario.threshold == 0 and max(p["Value"] for p in batch["MetricData"]) >= 1
        )

    # Per scenario, its logs and metrics land before its own ALARM call.
    order = [
        (name, p.get("AlarmName") or p.get("logGroupName"))
        for name, p in rig.calls
        if name in ("PutLogEvents", "PutMetricData", "SetAlarmState")
        and p.get("StateValue", "ALARM") == "ALARM"
    ]
    assert [name for name, _ in order] == ["PutLogEvents", "PutMetricData", "SetAlarmState"] * 8
    assert [key for name, key in order if name == "SetAlarmState"] == [
        s.alarm_name for s in SCENARIOS
    ]


def test_metrics_keep_each_alarm_breaching_for_the_following_ten_minutes(rig):
    rig.simulator().run("r1")

    fire_minute = NOW.replace(second=0, microsecond=0)
    for batch, scenario in zip(rig.named("PutMetricData"), SCENARIOS, strict=True):
        by_minute = {p["Timestamp"]: p["Value"] for p in batch["MetricData"]}
        for offset in range(11):
            assert by_minute[fire_minute + timedelta(minutes=offset)] > scenario.threshold
        assert len(batch["MetricData"]) <= 1000


def test_log_group_and_stream_creation_is_idempotent_with_one_day_retention():
    rig = Rig()
    rig.expect_all(already_exists=True)
    rig.logs_stub.activate()
    rig.cloudwatch_stub.activate()
    rig.sts_stub.activate()

    rig.simulator().run("r1")

    assert {p["retentionInDays"] for p in rig.named("PutRetentionPolicy")} == {1}
    assert [p["logGroupName"] for p in rig.named("CreateLogGroup")] == [
        s.log_group for s in SCENARIOS
    ]
    assert {p["logStreamName"] for p in rig.named("CreateLogStream")} == {"run-r1"}


def test_on_alarm_fired_is_called_after_each_alarm(rig):
    rig.simulator(with_hook=True).run("r1")

    assert rig.fired == [(s.alarm_name, "r1") for s in SCENARIOS]


def test_alarm_arn_builds_the_cloudwatch_alarm_arn():
    assert alarm_arn("us-east-1", "123456789012", "if-checkout") == (
        "arn:aws:cloudwatch:us-east-1:123456789012:alarm:if-checkout"
    )


def test_state_reason_data_is_valid_json(rig):
    rig.simulator().run("r1")

    firing = [p for p in rig.named("SetAlarmState") if p["StateValue"] == "ALARM"]
    assert json.loads(firing[0]["StateReasonData"]) == {"run_id": "r1"}
