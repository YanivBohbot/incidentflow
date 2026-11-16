"""Create synthetic CloudWatch alarms, metrics, and logs for every IncidentFlow demo scenario.

It extends seed_cloudwatch_demo.py (payment-service) to the other demo services. For each one it
creates, with the administrator profile used only for setup:

* the log group /incidentflow/demo/<service> (1-day retention) with healthy lines, then
  incident-specific error lines;
* a custom metric in IncidentFlow/Demo that spikes when the incident starts;
* an alarm if-<name> (see incidentflow.demo.scenarios) that enters ALARM on the spike.

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
from datetime import UTC, datetime, timedelta
from pathlib import Path

from seed_cloudwatch_demo import NAMESPACE, TAGS, aws, json_file, tag_alarm

from incidentflow.demo.scenarios import LEGACY_ALARM_NAMES, SCENARIOS, Scenario

# payment-service is seeded by seed_cloudwatch_demo.py, which also sets up the read-only role.
SEEDED_SCENARIOS = tuple(s for s in SCENARIOS if s.service != "payment-service")


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
    aws("cloudwatch", "put-metric-alarm", "--alarm-name", scenario.alarm_name,
        "--alarm-description", scenario.description,
        "--namespace", NAMESPACE, "--metric-name", scenario.metric,
        "--dimensions", f"Name=Service,Value={scenario.service}",
        "--statistic", "Maximum", "--period", "60", "--evaluation-periods", "3",
        "--threshold", str(scenario.threshold), "--comparison-operator", "GreaterThanThreshold",
        # Publishing stops after seeding; keep the last evaluated state.
        "--treat-missing-data", "ignore",
        "--tags", *[f"Key={key},Value={value}" for key, value in TAGS.items()], **run)
    tag_alarm(scenario, profile, region)
    print(f"seeded  {scenario.service:<22} alarm={scenario.alarm_name} log_group={scenario.log_group}")


def teardown(profile: str, region: str) -> None:
    run = {"profile": profile, "region": region}
    aws("cloudwatch", "delete-alarms", "--alarm-names", *[s.alarm_name for s in SCENARIOS],
        *LEGACY_ALARM_NAMES, **run, check=False)
    for scenario in SEEDED_SCENARIOS:
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
        for scenario in SEEDED_SCENARIOS:
            seed_scenario(scenario, arguments.profile, arguments.region, arguments.minutes_ago,
                          Path(temporary))
    groups = ",".join(["/incidentflow/demo/payment-service", *[s.log_group for s in SEEDED_SCENARIOS]])
    print("Alarms need up to three minutes to enter ALARM.")
    print(f"Set CLOUDWATCH_MCP_LOG_GROUPS={groups}")


if __name__ == "__main__":
    main()
