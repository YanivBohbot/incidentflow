"""Create synthetic CloudWatch alarms, metrics, and logs for every IncidentFlow demo scenario.

It extends seed_cloudwatch_demo.py (payment-service) to the other demo services. For each one it
creates, with the administrator profile used only for setup:

* the log group /incidentflow/demo/<service> (1-day retention) with healthy lines, then
  incident-specific error lines;
* a custom metric in IncidentFlow/Demo that spikes when the incident starts;
* an alarm incidentflow-demo-<service> that enters ALARM on the spike.

Every resource is tagged project=incidentflow. The CloudWatch agent reads only the last
CLOUDWATCH_MCP_LOOKBACK_MINUTES minutes, so re-run this script shortly before a demo.

Usage (from apps/api):
    python scripts/seed_cloudwatch_scenarios.py --profile default
    python scripts/seed_cloudwatch_scenarios.py --profile default --teardown
Then add the printed log groups to CLOUDWATCH_MCP_LOG_GROUPS.
"""

import argparse
import random
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from seed_cloudwatch_demo import NAMESPACE, TAGS, aws, json_file


@dataclass(frozen=True)
class Scenario:
    service: str
    metric: str
    unit: str
    baseline: tuple[int, int]
    incident: tuple[int, int]
    threshold: int
    healthy_line: str
    incident_lines: tuple[str, ...]

    @property
    def log_group(self) -> str:
        return f"/incidentflow/demo/{self.service}"

    @property
    def alarm(self) -> str:
        return f"incidentflow-demo-{self.service}"


SCENARIOS = (
    Scenario(
        "checkout-api", "HTTP503Count", "Count", (0, 1), (80, 140), 20,
        "INFO checkout-api POST /checkout status=200 latency_ms={ms}",
        (
            ("ERROR checkout-api POST /checkout status=503 error=PoolTimeoutError: waited 5000ms "
            "for a database connection (active=200 max=200)"),
            "WARN checkout-api autoscaler at max_pods=12 connections_per_pod=20",
        ),
    ),
    Scenario(
        "order-service", "ReplicaLagSeconds", "Seconds", (0, 2), (300, 360), 120,
        "INFO order-service GET /orders/history status=200 source=replica lag_s=1",
        (
            ("WARN order-service GET /orders/history status=200 source=replica lag_s=340 "
            "orders_missing_from_replica=17"),
            "INFO order-service POST /orders status=201 write_ack=primary",
        ),
    ),
    Scenario(
        "auth-service", "HTTP401Count", "Count", (2, 8), (600, 900), 100,
        "INFO auth-service POST /token/validate status=200 kid=2026-10",
        (
            ("ERROR auth-service POST /token/validate status=401 reason=unknown_kid kid=2026-11 "
            "jwks_cache_kids=[2026-10] jwks_cache_ttl=24h"),
            "WARN auth-service login failed for customer reason=token_rejected",
        ),
    ),
    Scenario(
        "inventory-service", "OOMKillCount", "Count", (0, 0), (1, 3), 0,
        "INFO inventory-service GET /stock status=200 version=2.4.1 memory_mib={ms}",
        (
            ("ERROR inventory-service container killed reason=OOMKilled memory_mib=2048 "
            "limit_mib=2048 version=2.4.1 stock_cache_entries=4100000"),
            "ERROR inventory-service GET /stock status=502 upstream=pod_restarting",
        ),
    ),
    Scenario(
        "search-api", "LatencyP95Ms", "Milliseconds", (150, 220), (2000, 2600), 1000,
        "INFO search-api GET /search status=200 latency_ms={ms} cache=hit",
        (
            ("WARN search-api GET /search status=200 latency_ms=2400 cache=miss "
            "redis=replica-after-failover"),
        ),
    ),
    Scenario(
        "notification-service", "EmailThrottledCount", "Count", (0, 2), (50, 90), 30,
        "INFO notification-service email sent status=202 type=order_confirmation",
        (
            ("WARN notification-service email provider status=429 rate_limited retry_in_s=60 "
            "backlog=12000"),
            "INFO notification-service email delivered delay_minutes=15 lost=0",
        ),
    ),
    Scenario(
        "refund-service", "HTTP502Count", "Count", (0, 1), (30, 60), 10,
        "INFO refund-service POST /refunds status=201 gateway_ms={ms}",
        (
            ("ERROR refund-service POST /refunds status=502 error=GatewayTimeout: payment-gateway "
            "did not answer within 2000ms (client timeout lowered in 3.1.0)"),
            "WARN refund-service refund queued for retry idempotency_key=present",
        ),
    ),
)


def _log_events(scenario: Scenario, incident_start: datetime, now: datetime) -> list[dict]:
    events, moment = [], incident_start - timedelta(minutes=20)
    while moment < now:
        if moment < incident_start:
            message = scenario.healthy_line.format(ms=random.randint(80, 200))
        else:
            message = random.choice(scenario.incident_lines)
        events.append({"timestamp": int(moment.timestamp() * 1000), "message": message})
        moment += timedelta(seconds=30)
    return events


def _metric_data(scenario: Scenario, incident_start: datetime, now: datetime) -> list[dict]:
    data, moment = [], incident_start - timedelta(minutes=20)
    while moment < now:
        low, high = scenario.incident if moment >= incident_start else scenario.baseline
        data.append(
            {
                "MetricName": scenario.metric,
                "Dimensions": [{"Name": "Service", "Value": scenario.service}],
                "Timestamp": moment.isoformat(),
                "Value": random.randint(low, high),
                "Unit": scenario.unit,
            }
        )
        moment += timedelta(minutes=1)
    return data


def seed_scenario(scenario: Scenario, profile: str, region: str, minutes_ago: int, directory: Path):
    now = datetime.now(UTC).replace(microsecond=0)
    incident_start = now - timedelta(minutes=minutes_ago)
    tags = ",".join(f"{key}={value}" for key, value in TAGS.items())
    run = {"profile": profile, "region": region}
    aws("logs", "create-log-group", "--log-group-name", scenario.log_group, "--tags", tags,
        **run, check=False)
    aws("logs", "put-retention-policy", "--log-group-name", scenario.log_group,
        "--retention-in-days", "1", **run)
    aws("logs", "create-log-stream", "--log-group-name", scenario.log_group,
        "--log-stream-name", f"{scenario.service}-1", **run, check=False)
    aws("logs", "put-log-events", "--log-group-name", scenario.log_group,
        "--log-stream-name", f"{scenario.service}-1", "--log-events",
        json_file(directory, f"{scenario.service}-logs.json",
                  _log_events(scenario, incident_start, now)), **run)
    aws("cloudwatch", "put-metric-data", "--namespace", NAMESPACE, "--metric-data",
        json_file(directory, f"{scenario.service}-metrics.json",
                  _metric_data(scenario, incident_start, now)), **run)
    aws("cloudwatch", "put-metric-alarm", "--alarm-name", scenario.alarm,
        "--alarm-description", f"Synthetic IncidentFlow demo: {scenario.service} {scenario.metric}.",
        "--namespace", NAMESPACE, "--metric-name", scenario.metric,
        "--dimensions", f"Name=Service,Value={scenario.service}",
        "--statistic", "Maximum", "--period", "60", "--evaluation-periods", "3",
        "--threshold", str(scenario.threshold), "--comparison-operator", "GreaterThanThreshold",
        # Publishing stops after seeding; keep the last evaluated state.
        "--treat-missing-data", "ignore",
        "--tags", *[f"Key={key},Value={value}" for key, value in TAGS.items()], **run)
    print(f"seeded  {scenario.service:<22} alarm={scenario.alarm} log_group={scenario.log_group}")


def teardown(profile: str, region: str) -> None:
    run = {"profile": profile, "region": region}
    aws("cloudwatch", "delete-alarms", "--alarm-names", *[s.alarm for s in SCENARIOS], **run,
        check=False)
    for scenario in SCENARIOS:
        aws("logs", "delete-log-group", "--log-group-name", scenario.log_group, **run, check=False)
    print("Deleted the scenario alarms and log groups. Custom metrics expire automatically.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="default", help="Administrator profile for setup only.")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--minutes-ago", type=int, default=30, help="Incident start before now.")
    parser.add_argument("--teardown", action="store_true")
    arguments = parser.parse_args()
    if arguments.teardown:
        teardown(arguments.profile, arguments.region)
        return
    with tempfile.TemporaryDirectory() as temporary:
        for scenario in SCENARIOS:
            seed_scenario(scenario, arguments.profile, arguments.region, arguments.minutes_ago,
                          Path(temporary))
    groups = ",".join(["/incidentflow/demo/payment-service", *[s.log_group for s in SCENARIOS]])
    print("Alarms need up to three minutes to enter ALARM.")
    print(f"Set CLOUDWATCH_MCP_LOG_GROUPS={groups}")


if __name__ == "__main__":
    main()
