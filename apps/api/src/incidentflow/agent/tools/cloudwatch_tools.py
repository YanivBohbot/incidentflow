"""ask_cloudwatch: the Supervisor's read-only AWS CloudWatch specialist.

One call does six steps:

1. Open the CloudWatch MCP server with the read-only AWS profile.
2. Read the alarms currently firing.
3. Read the metric behind each alarm of the service (at most three alarms).
4. Read recent error lines from the allowlisted log groups.
5. Ask the model once to turn this evidence into a CloudWatchFinding.
6. Drop every hypothesis that cites evidence the application did not collect.

A failed read is recorded in `errors` and the other reads continue.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from incidentflow.agent.agents_specialist.cloudwatch import build_cloudwatch_analysis_model
from incidentflow.agent.agents_specialist.contracts import (
    CloudWatchFinding,
    CloudWatchTimeWindow,
)
from incidentflow.agent.guardrails.external_evidence import mark_external_content_as_evidence
from incidentflow.agent.mcp_clients.cloudwatch import (
    CloudWatchMCPClient,
    CloudWatchPolicyError,
    CloudWatchResponseError,
    CloudWatchSession,
)
from incidentflow.agent.prompts.cloudwatch import CLOUDWATCH_ANALYSIS_SYSTEM_PROMPT
from incidentflow.core.config import get_settings

logger = logging.getLogger(__name__)

ERROR_LOGS_QUERY = (
    "fields @timestamp, @log, @message "
    r"| filter @message like /(?i)(error|exception|timeout|fatal|status=5\d\d)/ "
    "| sort @timestamp desc | limit 50"
)
MAX_ALARMS = 3
MAX_EVIDENCE_CHARACTERS = 6000
_OFFSET_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$"
)


@dataclass
class Evidence:
    """What the reads returned, keyed by the reference the model must cite."""

    items: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    signal_count: int = 0

    def add(self, reference: str, payload: object, signals: int) -> None:
        self.items[reference] = json.dumps(to_utc(payload), default=str)[:MAX_EVIDENCE_CHARACTERS]
        self.signal_count += signals

    def fail(self, operation: str, error: BaseException) -> None:
        self.errors.append(f"{operation}: {describe_error(error)}")


def to_utc(value: object) -> object:
    """Convert timestamps to UTC; the MCP server reports them in the host time zone."""
    if isinstance(value, dict):
        return {key: to_utc(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_utc(item) for item in value]
    if isinstance(value, str) and _OFFSET_TIMESTAMP.match(value):
        return datetime.fromisoformat(value).astimezone(UTC).isoformat()
    return value


def describe_error(error: BaseException) -> str:
    """Name the failure without copying AWS error text into the report."""
    if isinstance(error, CloudWatchPolicyError):
        return "rejected by the read-only policy"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, (CloudWatchResponseError, KeyError, TypeError)):
        return "malformed response"
    text = str(error).casefold()
    if "accessdenied" in text or "not authorized" in text:
        return "insufficient AWS permissions"
    if isinstance(error, (ConnectionError, OSError)):
        return "connection failed"
    return f"tool error ({type(error).__name__})"


async def _read_alarms(
    session: CloudWatchSession, evidence: Evidence, service_name: str | None
) -> list[dict[str, Any]]:
    """Step 2: read firing alarms and return the ones of the service to follow up."""
    try:
        alarms = await session.read("get_active_alarms", {"max_items": 20})
        metric_alarms = alarms["metric_alarms"]
        composite_alarms = alarms.get("composite_alarms") or []
    except Exception as error:  # noqa: BLE001 - keep the other reads.
        evidence.fail("get_active_alarms", error)
        return []
    evidence.add("alarms:active", alarms, len(metric_alarms) + len(composite_alarms))
    if service_name:
        metric_alarms = [
            alarm for alarm in metric_alarms if service_name.casefold() in str(alarm).casefold()
        ]
    return metric_alarms[:MAX_ALARMS]


async def _read_alarm_metrics(
    session: CloudWatchSession,
    evidence: Evidence,
    alarms: list[dict[str, Any]],
    window: dict[str, str],
) -> None:
    """Step 3: read the metric each alarm watches, so the model never invents a metric name."""
    for alarm in alarms:
        if not alarm.get("namespace") or not alarm.get("metric_name"):
            continue  # metric-math alarms have no single metric to read
        metric = f"{alarm['namespace']}/{alarm['metric_name']}"
        try:
            data = await session.read(
                "get_metric_data",
                {
                    "namespace": alarm["namespace"],
                    "metric_name": alarm["metric_name"],
                    "dimensions": [
                        {"name": dimension["Name"], "value": dimension["Value"]}
                        for dimension in alarm.get("dimensions") or []
                    ],
                    **window,
                    "statistic": "MAX",
                    "target_datapoints": 30,
                },
            )
            datapoints = sum(len(result["datapoints"]) for result in data["metricDataResults"])
        except Exception as error:  # noqa: BLE001 - keep the other reads.
            evidence.fail(f"get_metric_data {metric}", error)
            continue
        evidence.add(f"metric:{metric}", data, datapoints)


async def _read_error_logs(
    session: CloudWatchSession,
    evidence: Evidence,
    log_groups: tuple[str, ...],
    window: dict[str, str],
) -> None:
    """Step 4: read error, exception, timeout, and HTTP 5xx lines from allowlisted log groups."""
    if not log_groups:
        return
    try:
        logs = await session.read(
            "execute_log_insights_query",
            {
                "log_group_names": list(log_groups),
                **window,
                "query_string": ERROR_LOGS_QUERY,
                "limit": 50,
                "max_timeout": 30,
            },
        )
        lines = len(logs["results"])
    except Exception as error:  # noqa: BLE001 - keep the evidence already read.
        evidence.fail("execute_log_insights_query", error)
        return
    evidence.add(f"logs:{','.join(log_groups)}", logs, lines)


async def _analyse(
    incident_context: str, service_name: str | None, window: dict[str, str], evidence: Evidence
) -> CloudWatchFinding:
    """Step 5: one structured model call; the model cannot call tools."""
    evidence_blocks = [
        mark_external_content_as_evidence(reference, content)
        for reference, content in evidence.items.items()
    ]
    result = await build_cloudwatch_analysis_model().ainvoke(
        [
            SystemMessage(content=CLOUDWATCH_ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Incident context:\n{incident_context}\n\n"
                    f"Service: {service_name or 'not specified'}\n"
                    f"Queried window (UTC): {window['start_time']} to {window['end_time']}\n"
                    f"Available evidence references: {', '.join(evidence.items)}\n"
                    f"Failed CloudWatch reads: {', '.join(evidence.errors) or 'none'}\n\n"
                    "CloudWatch evidence collected by the application:\n"
                    + "\n\n".join(evidence_blocks)
                )
            ),
        ]
    )
    # with_structured_output is typed as "dict or model"; validate to get a CloudWatchFinding.
    return CloudWatchFinding.model_validate(result)


def _keep_cited_hypotheses(finding: CloudWatchFinding, references: list[str]) -> CloudWatchFinding:
    """Step 6: keep only hypotheses that cite evidence the application actually collected."""
    hypotheses = [
        hypothesis
        for hypothesis in finding.root_cause_hypotheses
        if set(hypothesis.supporting_evidence) <= set(references)
    ]
    observations = list(finding.observations)
    if len(hypotheses) < len(finding.root_cause_hypotheses):
        observations.append("Hypotheses citing evidence that was not collected were removed.")
    return finding.model_copy(
        update={
            "root_cause_hypotheses": hypotheses,
            "observations": observations,
            "evidence_references": references,
        }
    )


def _create_cloudwatch_mcp_client() -> CloudWatchMCPClient:
    settings = get_settings()
    return CloudWatchMCPClient(
        settings.cloudwatch_mcp_command,
        settings.cloudwatch_mcp_stdio_arguments,
        aws_region=settings.cloudwatch_mcp_aws_region,
        aws_profile=settings.cloudwatch_mcp_aws_profile,
        allowed_log_groups=settings.cloudwatch_mcp_allowed_log_groups,
    )


async def _investigate(
    incident_context: str, service_name: str | None, incident_id: str | None
) -> CloudWatchFinding:
    settings = get_settings()
    end = datetime.now(UTC).replace(microsecond=0)
    start = end - timedelta(minutes=settings.cloudwatch_mcp_lookback_minutes)
    window = {"start_time": start.isoformat(), "end_time": end.isoformat()}
    evidence = Evidence()
    try:
        # One time budget covers server start-up and every read. Evidence read before a
        # timeout is kept, because it lives outside the cancelled block.
        async with asyncio.timeout(settings.cloudwatch_mcp_timeout_seconds):
            async with _create_cloudwatch_mcp_client().open_read_session() as session:
                alarms = await _read_alarms(session, evidence, service_name)
                await _read_alarm_metrics(session, evidence, alarms, window)
                await _read_error_logs(
                    session, evidence, settings.cloudwatch_mcp_allowed_log_groups, window
                )
    except Exception as error:  # noqa: BLE001 - CloudWatch must never fail the investigation.
        logger.warning("CloudWatch MCP session failed: %s", type(error).__name__)
        evidence.fail("cloudwatch_mcp", error)

    # The application, not the model, decides these fields.
    facts = {
        "incident_id": incident_id,
        "service_name": service_name,
        "time_window": CloudWatchTimeWindow(**window),
        "errors": evidence.errors,
        "investigation_status": "partial" if evidence.errors else "completed",
    }
    if not evidence.items:
        return CloudWatchFinding(
            **{**facts, "investigation_status": "unavailable"},
            summary="Live CloudWatch MCP was unavailable during this investigation.",
            confidence=0,
        )
    if evidence.signal_count == 0:
        return CloudWatchFinding(
            **facts,
            summary=(
                "CloudWatch returned no active alarm, metric datapoint, or matching log event "
                "in the queried window."
            ),
            evidence_references=list(evidence.items),
            confidence=0,
        )
    finding = await _analyse(incident_context, service_name, window, evidence)
    return _keep_cited_hypotheses(finding, list(evidence.items)).model_copy(update=facts)


@tool(
    "ask_cloudwatch",
    description=(
        "Read recent AWS CloudWatch alarms, metrics, and error logs (read-only). Use for "
        "production symptoms such as HTTP 5xx errors, latency, or alarms."
    ),
)
async def ask_cloudwatch(
    incident_context: str, service_name: str | None = None, incident_id: str | None = None
) -> str:
    """Delegate an incident question to the read-only CloudWatch Observability Agent."""
    if not get_settings().cloudwatch_mcp_enabled:
        finding = CloudWatchFinding(
            incident_id=incident_id,
            service_name=service_name,
            investigation_status="unavailable",
            summary="Live CloudWatch MCP is unavailable because CLOUDWATCH_MCP_ENABLED is false.",
            confidence=0,
        )
        return finding.model_dump_json()
    try:
        finding = await _investigate(incident_context, service_name, incident_id)
    except Exception as error:
        logger.exception("CloudWatch specialist delegation failed")
        finding = CloudWatchFinding(
            incident_id=incident_id,
            service_name=service_name,
            investigation_status="unavailable",
            summary="Live CloudWatch MCP was unavailable during this investigation.",
            errors=[f"analysis: {describe_error(error)}"],
            confidence=0,
        )
    return finding.model_dump_json()
