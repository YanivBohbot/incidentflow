"""Create or remove a synthetic CloudWatch incident for the CloudWatch Observability Agent.

The setup profile (an administrator profile) is used only by this script. It creates:

* the log group /incidentflow/demo/payment-service with synthetic HTTP 500 and MongoDB pool logs;
* custom metric IncidentFlow/Demo HTTP5xxCount for payment-service;
* the alarm if-payments, which enters ALARM on the synthetic 5xx spike;
* the role IncidentFlowCloudWatchReadOnly with read-only CloudWatch permissions;
* the AWS CLI profile "incidentflow" that assumes this role from the setup profile.

With --create-demo-role it instead creates only the role IncidentFlowDemoSimulator (the local
demo simulator's write access, scoped like the cloud DemoFunction) and the profile
"incidentflow-demo".

The agent then uses only the read-only profile. Run with --teardown to delete the AWS resources.
The AWS CLI is used instead of boto3 so the API does not gain a runtime dependency.
"""

import argparse
import json
import random
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from incidentflow.demo.scenarios import (
    LEGACY_ALARM_NAMES,
    METRIC_NAMESPACE,
    SCENARIOS,
    Scenario,
)

LOG_GROUP = "/incidentflow/demo/payment-service"
LOG_STREAM = "payment-service-1"
NAMESPACE = METRIC_NAMESPACE
SERVICE = "payment-service"
ROLE_NAME = "IncidentFlowCloudWatchReadOnly"
READ_PROFILE = "incidentflow"
DEMO_ROLE_NAME = "IncidentFlowDemoSimulator"
DEMO_PROFILE = "incidentflow-demo"
TAGS = {"project": "incidentflow", "purpose": "cloudwatch-agent-demo"}


def _payment_scenario() -> Scenario:
    for scenario in SCENARIOS:
        if scenario.service == SERVICE:
            return scenario
    raise RuntimeError(f"No demo scenario for service {SERVICE!r} in incidentflow.demo.scenarios")


PAYMENT = _payment_scenario()
ALARM_NAME = PAYMENT.alarm_name

READ_ONLY_ACTIONS = [
    "cloudwatch:DescribeAlarms",
    "cloudwatch:GetMetricData",
    "cloudwatch:ListMetrics",
    "logs:DescribeLogGroups",
    "logs:DescribeQueryDefinitions",
    "logs:ListLogAnomalyDetectors",
    "logs:ListAnomalies",
    "logs:StartQuery",
    "logs:GetQueryResults",
    "logs:StopQuery",
]


def demo_role_policy(account: str, region: str) -> dict:
    """Permissions of the demo simulator; mirrors the cloud DemoFunction in infra/cdk."""
    group = f"arn:aws:logs:{region}:{account}:log-group:/incidentflow/demo/*"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:TagResource"],
                "Resource": [group],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [group, f"{group}:*"],
            },
            {
                "Effect": "Allow",
                "Action": ["cloudwatch:PutMetricData"],
                "Resource": "*",
                "Condition": {"StringEquals": {"cloudwatch:namespace": NAMESPACE}},
            },
            {
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:PutMetricAlarm",
                    "cloudwatch:SetAlarmState",
                    "cloudwatch:TagResource",
                    "cloudwatch:DescribeAlarms",
                ],
                "Resource": [f"arn:aws:cloudwatch:{region}:{account}:alarm:if-*"],
            },
        ],
    }


def aws(*arguments: str, profile: str, region: str, check: bool = True) -> str:
    result = subprocess.run(
        ["aws", *arguments, "--profile", profile, "--region", region, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"aws {' '.join(arguments[:2])} failed: {result.stderr.strip()}")
    return result.stdout


def incident_tags_json(scenario: Scenario) -> str:
    """The tags cloud ingestion reads; put-metric-alarm only applies tags on first creation."""
    return json.dumps(
        [
            {"Key": "incidentflow:title", "Value": scenario.title},
            {"Key": "incidentflow:priority", "Value": scenario.priority.value},
            {"Key": "incidentflow:service", "Value": scenario.service},
        ]
    )


def tag_alarm(scenario: Scenario, profile: str, region: str) -> None:
    identity = json.loads(aws("sts", "get-caller-identity", profile=profile, region=region))
    arn = f"arn:aws:cloudwatch:{region}:{identity['Account']}:alarm:{scenario.alarm_name}"
    aws(
        "cloudwatch",
        "tag-resource",
        "--resource-arn",
        arn,
        "--tags",
        incident_tags_json(scenario),
        profile=profile,
        region=region,
    )


def json_file(directory: Path, name: str, payload: object) -> str:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return f"file://{path.as_posix()}"


def synthetic_log_events(
    incident_start: datetime, log_start: datetime, now: datetime
) -> list[dict[str, object]]:
    """Healthy traffic before the incident, then the scenario's error lines.

    Logs Insights ignores events dated before the log group's creation, so the caller passes
    the earliest queryable moment as log_start. A freshly created group therefore receives the
    synthetic events compressed into the seconds after its creation.
    """
    events = []
    step = max((now - log_start) / 120, timedelta(milliseconds=100))
    moment = log_start
    while moment < now:
        timestamp = int(moment.timestamp() * 1000)
        if moment < incident_start:
            message = PAYMENT.healthy_line.format(ms=random.randint(80, 160))
        else:
            message = random.choice(PAYMENT.incident_lines)
        events.append({"timestamp": timestamp, "message": message})
        moment += step
    return events


def synthetic_metric_data(incident_start: datetime, now: datetime) -> list[dict[str, object]]:
    data = []
    moment = incident_start - timedelta(minutes=20)
    dimensions = [{"Name": "Service", "Value": SERVICE}]
    while moment < now:
        low, high = PAYMENT.incident if moment >= incident_start else PAYMENT.baseline
        data.append(
            {
                "MetricName": PAYMENT.metric,
                "Dimensions": dimensions,
                "Timestamp": moment.isoformat(),
                "Value": random.randint(low, high),
                "Unit": PAYMENT.unit,
            }
        )
        moment += timedelta(minutes=1)
    return data


def log_group_creation(profile: str, region: str) -> datetime:
    groups = json.loads(
        aws(
            "logs",
            "describe-log-groups",
            "--log-group-name-prefix",
            LOG_GROUP,
            profile=profile,
            region=region,
        )
    )["logGroups"]
    created = next(group["creationTime"] for group in groups if group["logGroupName"] == LOG_GROUP)
    return datetime.fromtimestamp(created / 1000 + 1, UTC)


def seed(profile: str, region: str, minutes_ago: int, *, logs_only: bool = False) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    incident_start = now - timedelta(minutes=minutes_ago)
    account = json.loads(aws("sts", "get-caller-identity", profile=profile, region=region))
    caller_arn = account["Arn"]

    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        aws(
            "logs",
            "create-log-group",
            "--log-group-name",
            LOG_GROUP,
            "--tags",
            ",".join(f"{key}={value}" for key, value in TAGS.items()),
            profile=profile,
            region=region,
            check=False,
        )
        aws(
            "logs",
            "put-retention-policy",
            "--log-group-name",
            LOG_GROUP,
            "--retention-in-days",
            "1",
            profile=profile,
            region=region,
        )
        aws(
            "logs",
            "create-log-stream",
            "--log-group-name",
            LOG_GROUP,
            "--log-stream-name",
            LOG_STREAM,
            profile=profile,
            region=region,
            check=False,
        )
        now = datetime.now(UTC)
        log_start = max(incident_start - timedelta(minutes=20), log_group_creation(profile, region))
        aws(
            "logs",
            "put-log-events",
            "--log-group-name",
            LOG_GROUP,
            "--log-stream-name",
            LOG_STREAM,
            "--log-events",
            json_file(
                directory, "events.json", synthetic_log_events(incident_start, log_start, now)
            ),
            profile=profile,
            region=region,
        )
        if logs_only:
            print(f"Wrote synthetic logs from {log_start.isoformat()} (UTC).")
            return

        metric_data = synthetic_metric_data(incident_start, now)
        for index in range(0, len(metric_data), 500):
            aws(
                "cloudwatch",
                "put-metric-data",
                "--namespace",
                NAMESPACE,
                "--metric-data",
                json_file(directory, f"metrics-{index}.json", metric_data[index : index + 500]),
                profile=profile,
                region=region,
            )

        aws(
            "cloudwatch",
            "put-metric-alarm",
            "--alarm-name",
            ALARM_NAME,
            "--alarm-description",
            PAYMENT.description,
            "--namespace",
            NAMESPACE,
            "--metric-name",
            PAYMENT.metric,
            "--dimensions",
            f"Name=Service,Value={SERVICE}",
            "--statistic",
            "Sum",
            "--period",
            "60",
            "--evaluation-periods",
            "3",
            "--threshold",
            str(PAYMENT.threshold),
            "--comparison-operator",
            "GreaterThanThreshold",
            # The demo stops publishing data after seeding; keep the last evaluated state.
            "--treat-missing-data",
            "ignore",
            "--tags",
            *[f"Key={key},Value={value}" for key, value in TAGS.items()],
            profile=profile,
            region=region,
        )
        tag_alarm(PAYMENT, profile, region)

        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Principal": {"AWS": caller_arn}, "Action": "sts:AssumeRole"}
            ],
        }
        read_policy = {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": READ_ONLY_ACTIONS, "Resource": "*"}],
        }
        created = aws(
            "iam",
            "create-role",
            "--role-name",
            ROLE_NAME,
            "--assume-role-policy-document",
            json_file(directory, "trust.json", trust_policy),
            "--description",
            "Read-only CloudWatch access for the IncidentFlow CloudWatch agent.",
            "--tags",
            *[f"Key={key},Value={value}" for key, value in TAGS.items()],
            profile=profile,
            region=region,
            check=False,
        )
        role_arn = (
            json.loads(created)["Role"]["Arn"]
            if created
            else f"arn:aws:iam::{account['Account']}:role/{ROLE_NAME}"
        )
        aws(
            "iam",
            "put-role-policy",
            "--role-name",
            ROLE_NAME,
            "--policy-name",
            "CloudWatchReadOnlyForIncidentFlow",
            "--policy-document",
            json_file(directory, "read.json", read_policy),
            profile=profile,
            region=region,
        )

    for key, value in {"role_arn": role_arn, "source_profile": profile, "region": region}.items():
        subprocess.run(
            ["aws", "configure", "set", key, value, "--profile", READ_PROFILE], check=True
        )

    print(f"Synthetic incident started at {incident_start.isoformat()} (UTC).")
    print(f"Read-only profile: {READ_PROFILE} -> {role_arn}")
    print("The alarm needs up to three minutes to enter ALARM.")
    print("Configure the API with:")
    print("  CLOUDWATCH_MCP_ENABLED=true")
    print(f"  CLOUDWATCH_MCP_AWS_PROFILE={READ_PROFILE}")
    print(f"  CLOUDWATCH_MCP_AWS_REGION={region}")
    print(f"  CLOUDWATCH_MCP_LOG_GROUPS={LOG_GROUP}")


def create_demo_role(profile: str, region: str) -> None:
    identity = json.loads(aws("sts", "get-caller-identity", profile=profile, region=region))
    account = identity["Account"]
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Principal": {"AWS": identity["Arn"]}, "Action": "sts:AssumeRole"}
        ],
    }
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        try:
            created = aws(
                "iam",
                "create-role",
                "--role-name",
                DEMO_ROLE_NAME,
                "--assume-role-policy-document",
                json_file(directory, "trust.json", trust_policy),
                "--description",
                "Lets the local IncidentFlow demo simulator write demo logs, metrics and alarms.",
                "--tags",
                "Key=project,Value=incidentflow",
                profile=profile,
                region=region,
            )
            role_arn = json.loads(created)["Role"]["Arn"]
        except RuntimeError:
            # Re-running is fine when the role exists; any other failure must surface.
            existing = aws(
                "iam",
                "get-role",
                "--role-name",
                DEMO_ROLE_NAME,
                profile=profile,
                region=region,
                check=False,
            )
            if not existing:
                raise
            role_arn = f"arn:aws:iam::{account}:role/{DEMO_ROLE_NAME}"
        aws(
            "iam",
            "put-role-policy",
            "--role-name",
            DEMO_ROLE_NAME,
            "--policy-name",
            "DemoSimulatorForIncidentFlow",
            "--policy-document",
            json_file(directory, "demo.json", demo_role_policy(account, region)),
            profile=profile,
            region=region,
        )
    for key, value in {"role_arn": role_arn, "source_profile": profile, "region": region}.items():
        subprocess.run(
            ["aws", "configure", "set", key, value, "--profile", DEMO_PROFILE], check=True
        )
    print(f"Demo profile: {DEMO_PROFILE} -> {role_arn}")
    print("Configure the API with:")
    print("  DEMO_ENABLED=true")
    print(f"  DEMO_AWS_PROFILE={DEMO_PROFILE}")


def teardown(profile: str, region: str) -> None:
    aws(
        "cloudwatch",
        "delete-alarms",
        "--alarm-names",
        ALARM_NAME,
        *LEGACY_ALARM_NAMES,
        profile=profile,
        region=region,
        check=False,
    )
    aws(
        "logs",
        "delete-log-group",
        "--log-group-name",
        LOG_GROUP,
        profile=profile,
        region=region,
        check=False,
    )
    aws(
        "iam",
        "delete-role-policy",
        "--role-name",
        ROLE_NAME,
        "--policy-name",
        "CloudWatchReadOnlyForIncidentFlow",
        profile=profile,
        region=region,
        check=False,
    )
    aws("iam", "delete-role", "--role-name", ROLE_NAME, profile=profile, region=region, check=False)
    print("Deleted the demo alarm, log group, and read-only role.")
    print(f"Custom metrics in {NAMESPACE} expire automatically; they cannot be deleted.")
    print(
        f"Remove the [profile {READ_PROFILE}] section from ~/.aws/config if it is no longer needed."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", default="default", help="Administrator profile for setup only."
    )
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--minutes-ago", type=int, default=40, help="Incident start before now.")
    parser.add_argument(
        "--logs-only", action="store_true", help="Only append logs to the existing log group."
    )
    parser.add_argument(
        "--create-demo-role",
        action="store_true",
        help="Only create the IncidentFlowDemoSimulator role and the incidentflow-demo profile.",
    )
    parser.add_argument("--teardown", action="store_true")
    arguments = parser.parse_args()
    if arguments.create_demo_role:
        create_demo_role(arguments.profile, arguments.region)
    elif arguments.teardown:
        teardown(arguments.profile, arguments.region)
    else:
        seed(
            arguments.profile,
            arguments.region,
            arguments.minutes_ago,
            logs_only=arguments.logs_only,
        )


if __name__ == "__main__":
    main()
