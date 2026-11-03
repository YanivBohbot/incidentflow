"""ask_cloudwatch: the Supervisor delegates to the CloudWatch Observability Agent.

This is the "subagent as a tool" pattern. One call:

1. Opens the CloudWatch MCP server with the read-only AWS profile (three approved tools).
2. Runs the CloudWatch create_agent: the agent decides which alarms, metrics, and logs to read.
   Its middleware enforces the read-only policy and bounds the loop.
3. Applies application guardrails to the agent's CloudWatchFinding:
   - evidence references come from the reads that actually succeeded, never from the model;
   - a hypothesis citing evidence that was not read is removed;
   - status, time window, and errors are set by code.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain.tools import tool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from incidentflow.agent.agents_specialist.cloudwatch import (
    build_cloudwatch_agent,
    describe_error,
    to_utc,
)
from incidentflow.agent.findings import CloudWatchFinding, CloudWatchTimeWindow
from incidentflow.agent.guardrails.external_evidence import unwrap_external_evidence
from incidentflow.agent.mcp_clients.cloudwatch import CloudWatchMCPClient
from incidentflow.agent.tools.subagent_runtime import subagent_config
from incidentflow.core.config import get_settings

__all__ = ["ask_cloudwatch", "describe_error", "to_utc"]

logger = logging.getLogger(__name__)

ERROR_LOGS_QUERY = (
    "fields @timestamp, @log, @message "
    r"| filter @message like /(?i)(error|exception|timeout|fatal|status=5\d\d)/ "
    "| sort @timestamp desc | limit 50"
)
UNAVAILABLE_SUMMARY = "Live CloudWatch MCP was unavailable during this investigation."


def _task(
    incident_context: str, service_name: str | None, window: dict[str, str], log_groups: str
) -> str:
    """The delegation message: what to investigate, and the exact read parameters."""
    return (
        f"Incident context:\n{incident_context}\n\n"
        f"Service: {service_name or 'not specified'}\n"
        f"Time window (UTC): start_time={window['start_time']} end_time={window['end_time']}\n"
        f"Allowed log groups: {log_groups}\n\n"
        "Read parameters:\n"
        "- get_active_alarms: max_items=20.\n"
        "- get_metric_data: namespace, metric_name, and dimensions ([{name, value}]) of a "
        "relevant alarm, the time window above, statistic=MAX, target_datapoints=30.\n"
        "- execute_log_insights_query: log_group_names from the allowed list, the time window "
        f"above, limit=50, max_timeout=30, query_string exactly:\n{ERROR_LOGS_QUERY}"
    )


def _reference(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """The evidence reference a successful read produces."""
    if tool_name == "get_active_alarms":
        return "alarms:active"
    if tool_name == "get_metric_data":
        return f"metric:{arguments.get('namespace')}/{arguments.get('metric_name')}"
    if tool_name == "execute_log_insights_query":
        return f"logs:{','.join(arguments.get('log_group_names') or [])}"
    return None


def _signals(tool_name: str, content: Any) -> int:
    """Count alarms, datapoints, or log lines returned by one read."""
    try:
        payload = json.loads(str(content))
        if tool_name == "get_active_alarms":
            return len(payload.get("metric_alarms") or []) + len(
                payload.get("composite_alarms") or []
            )
        if tool_name == "get_metric_data":
            return sum(len(item["datapoints"]) for item in payload["metricDataResults"])
        if tool_name == "execute_log_insights_query":
            return len(payload.get("results") or [])
    except (ValueError, KeyError, TypeError, AttributeError):
        return 0
    return 0


def collect_reads(messages: list[BaseMessage]) -> tuple[list[str], list[str], int]:
    """From the agent's messages: references read, failed reads, and the signal count."""
    calls = {
        call["id"]: call
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    references: list[str] = []
    errors: list[str] = []
    signals = 0
    for message in messages:
        if not isinstance(message, ToolMessage) or message.tool_call_id not in calls:
            continue
        call = calls[message.tool_call_id]
        reference = _reference(call["name"], call.get("args", {}))
        if reference is None:
            continue  # the structured-output tool, not a CloudWatch read
        content = unwrap_external_evidence(message.content)
        if message.status == "error":
            errors.append(content.replace(" failed: ", ": ", 1))
            continue
        if reference not in references:
            references.append(reference)
        signals += _signals(call["name"], content)
    return references, errors, signals


def keep_cited_hypotheses(finding: CloudWatchFinding, references: list[str]) -> CloudWatchFinding:
    """Keep only hypotheses that cite evidence the agent actually read."""
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
    incident_context: str,
    service_name: str | None,
    incident_id: str | None,
    config: RunnableConfig | None,
) -> CloudWatchFinding:
    settings = get_settings()
    end = datetime.now(UTC).replace(microsecond=0)
    start = end - timedelta(minutes=settings.cloudwatch_mcp_lookback_minutes)
    window = {"start_time": start.isoformat(), "end_time": end.isoformat()}
    facts: dict[str, Any] = {
        "incident_id": incident_id,
        "service_name": service_name,
        "time_window": CloudWatchTimeWindow(**window),
    }
    task = _task(
        incident_context, service_name, window, ", ".join(settings.cloudwatch_mcp_allowed_log_groups)
    )
    try:
        # One time budget covers server start-up and the whole agent run.
        async with asyncio.timeout(settings.cloudwatch_mcp_timeout_seconds):
            async with _create_cloudwatch_mcp_client().open_read_session() as session:
                agent = build_cloudwatch_agent(list(session.tools.values()))
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=task)]}, config=subagent_config(config)
                )
    except Exception as error:  # noqa: BLE001 - CloudWatch must never fail the investigation.
        logger.warning("CloudWatch agent failed: %s", type(error).__name__)
        return CloudWatchFinding(
            **facts,
            investigation_status="unavailable",
            summary=UNAVAILABLE_SUMMARY,
            errors=[f"cloudwatch_mcp: {describe_error(error)}"],
            confidence=0,
        )

    references, errors, signals = collect_reads(result.get("messages", []))
    facts["errors"] = errors
    facts["investigation_status"] = "partial" if errors else "completed"
    if not references:
        return CloudWatchFinding(
            **{**facts, "investigation_status": "unavailable"},
            summary=UNAVAILABLE_SUMMARY,
            confidence=0,
        )
    finding = result.get("structured_response")
    if signals == 0 or finding is None:
        # Nothing firing, or the agent stopped before answering: never invent a cause.
        return CloudWatchFinding(
            **facts,
            summary=(
                "CloudWatch returned no active alarm, metric datapoint, or matching log event "
                "in the queried window."
                if signals == 0
                else "The CloudWatch agent stopped before writing its finding."
            ),
            evidence_references=references,
            confidence=0,
        )
    finding = CloudWatchFinding.model_validate(finding)
    return keep_cited_hypotheses(finding, references).model_copy(update=facts)


@tool(
    "ask_cloudwatch",
    description=(
        "Delegate to the CloudWatch Observability Agent, which reads recent AWS CloudWatch "
        "alarms, metrics, and error logs (read-only). Use for production symptoms such as "
        "HTTP 5xx errors, latency, or alarms."
    ),
)
async def ask_cloudwatch(
    incident_context: str,
    config: RunnableConfig,
    service_name: str | None = None,
    incident_id: str | None = None,
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
        finding = await _investigate(incident_context, service_name, incident_id, config)
    except Exception as error:
        logger.exception("CloudWatch specialist delegation failed")
        finding = CloudWatchFinding(
            incident_id=incident_id,
            service_name=service_name,
            investigation_status="unavailable",
            summary=UNAVAILABLE_SUMMARY,
            errors=[f"analysis: {describe_error(error)}"],
            confidence=0,
        )
    return finding.model_dump_json()
