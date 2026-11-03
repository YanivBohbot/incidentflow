"""Create or remove a synthetic CloudWatch incident for the CloudWatch Observability Agent.

The setup profile (an administrator profile) is used only by this script. It creates:

* the log group /incidentflow/demo/payment-service with synthetic HTTP 500 and MongoDB pool logs;
* custom metrics IncidentFlow/Demo HTTP5xxCount and LatencyP95Ms for payment-service;
* the alarm incidentflow-demo-payment-5xx, which enters ALARM on the synthetic 5xx spike;
* the role IncidentFlowCloudWatchReadOnly with read-only CloudWatch permissions;
* the AWS CLI profile "incidentflow" that assumes this role from the setup profile.

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

LOG_GROUP = "/incidentflow/demo/payment-service"
LOG_STREAM = "payment-service-1"
NAMESPACE = "IncidentFlow/Demo"
SERVICE = "payment-service"
ALARM_NAME = "incidentflow-demo-payment-5xx"
ROLE_NAME = "IncidentFlowCloudWatchReadOnly"
READ_PROFILE = "incidentflow"
TAGS = {"project": "incidentflow", "purpose": "cloudwatch-agent-demo"}

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


def json_file(directory: Path, name: str, payload: object) -> str:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return f"file://{path.as_posix()}"


def synthetic_log_events(
    incident_start: datetime, log_start: datetime, now: datetime
) -> list[dict[str, object]]:
    """Healthy traffic before the incident, then 500s caused by MongoDB pool timeouts.

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
            message = (
                f"INFO {SERVICE} POST /payments status=200 latency_ms={random.randint(80, 160)}"
            )
        elif random.random() < 0.6:
            message = (
                f"ERROR {SERVICE} POST /payments status=500 latency_ms={random.randint(5000, 5200)} "
                "error=MongoTimeoutError: Timed out while checking out a connection from "
                "connection pool (maxPoolSize=20, waitQueueTimeoutMS=5000)"
            )
        else:
            message = (
                f"WARN {SERVICE} mongodb connection pool exhausted "
                "in_use=20 max_pool_size=20 wait_queue=37"
            )
        events.append({"timestamp": timestamp, "message": message})
        moment += step
    return events


def synthetic_metric_data(incident_start: datetime, now: datetime) -> list[dict[str, object]]:
    data = []
    moment = incident_start - timedelta(minutes=20)
    dimensions = [{"Name": "Service", "Value": SERVICE}]
    while moment < now:
        incident = moment >= incident_start
        data.append(
            {
                "MetricName": "HTTP5xxCount",
                "Dimensions": dimensions,
                "Timestamp": moment.isoformat(),
                "Value": random.randint(40, 70) if incident else random.randint(0, 1),
                "Unit": "Count",
            }
        )
        data.append(
            {
                "MetricName": "LatencyP95Ms",
                "Dimensions": dimensions,
                "Timestamp": moment.isoformat(),
                "Value": random.randint(4800, 5200) if incident else random.randint(120, 180),
                "Unit": "Milliseconds",
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
            "Synthetic IncidentFlow demo: payment-service HTTP 5xx spike.",
            "--namespace",
            NAMESPACE,
            "--metric-name",
            "HTTP5xxCount",
            "--dimensions",
            f"Name=Service,Value={SERVICE}",
            "--statistic",
            "Sum",
            "--period",
            "60",
            "--evaluation-periods",
            "3",
            "--threshold",
            "10",
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


def teardown(profile: str, region: str) -> None:
    aws(
        "cloudwatch",
        "delete-alarms",
        "--alarm-names",
        ALARM_NAME,
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
    parser.add_argument("--teardown", action="store_true")
    arguments = parser.parse_args()
    if arguments.teardown:
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
