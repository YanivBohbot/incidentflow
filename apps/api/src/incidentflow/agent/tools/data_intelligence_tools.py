"""ask_data_intelligence: the Supervisor delegates to the Data Intelligence Agent.

The agent (a create_agent) reads the event collection schema, then writes one bounded
aggregate (or find) query over the read-only MongoDB MCP tools, and returns a
DataIntelligenceFinding. The application marks synthetic datasets deterministically.
"""

import json
import logging
import re

from langchain.tools import tool
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from incidentflow.agent.agents_specialist.data_intelligence import build_data_intelligence_agent
from incidentflow.agent.findings import DataIntelligenceFinding
from incidentflow.agent.guardrails.external_evidence import unwrap_external_evidence
from incidentflow.agent.mcp_clients.mongodb import MongoDBMCPClient
from incidentflow.agent.tools.subagent_runtime import subagent_config
from incidentflow.core.config import get_settings

logger = logging.getLogger(__name__)

EVENT_LIMIT = 20
_SERVICE_SUFFIXES = ("service", "svc", "api")


def service_name_pattern(service_name: str) -> str:
    """Match a service whatever its suffix: payment-service, payment-api and Payment API match.

    Incident reports and event producers rarely name a service the same way, so the base name
    is matched case-insensitively with an optional -service/-api/-svc suffix.
    """
    tokens = [token for token in re.split(r"[\s_-]+", service_name.casefold().strip()) if token]
    while len(tokens) > 1 and tokens[-1] in _SERVICE_SUFFIXES:
        tokens.pop()
    base = "[-_ ]?".join(re.escape(token) for token in tokens)
    return rf"^{base}([-_ ]?({'|'.join(_SERVICE_SUFFIXES)}))?$"


def events_pipeline(service_name: str | None) -> list[dict]:
    """Time-ordered events of one service, or the most recent events when none is named."""
    if not service_name:
        return [{"$sort": {"timestamp": -1}}, {"$limit": EVENT_LIMIT}, {"$sort": {"timestamp": 1}}]
    return [
        {"$match": {"service": {"$regex": service_name_pattern(service_name), "$options": "i"}}},
        {"$sort": {"timestamp": -1}},
        {"$limit": EVENT_LIMIT},
        {"$sort": {"timestamp": 1}},
    ]


def _is_synthetic_dataset(events_result: object) -> bool:
    """Recognize explicit test markers without confusing a live integration with production data."""
    event_text = str(events_result).casefold()
    return "synthetic" in event_text or "test_run" in event_text


def _classify_dataset(
    finding: DataIntelligenceFinding,
    *,
    is_synthetic: bool,
) -> DataIntelligenceFinding:
    """Attach a deterministic dataset classification to the model's technical interpretation."""
    if not is_synthetic:
        return finding

    limitation = (
        "MongoDB returned a synthetic test dataset; it validates the investigation flow but "
        "cannot establish a production incident root cause."
    )
    limitations = list(dict.fromkeys([*finding.limitations, limitation]))
    return finding.model_copy(
        update={
            "data_classification": "synthetic",
            "limitations": limitations,
        }
    )


def _task(incident_context: str, service_name: str | None, database: str, collection: str) -> str:
    """The delegation message: the incident, the target collection, and a suggested query."""
    pipeline = json.dumps(events_pipeline(service_name))
    return (
        f"Incident context:\n{incident_context}\n\n"
        f"Service: {service_name or 'not specified'}\n"
        f"Database: {database}\nCollection: {collection}\n"
        "Suggested aggregate pipeline (matches the service and its naming variants):\n"
        f"{pipeline}"
    )


def _read_results(messages: list[BaseMessage]) -> str:
    """Concatenate what the agent's successful aggregate/find reads returned."""
    return "\n".join(
        unwrap_external_evidence(message.content)
        for message in messages
        if isinstance(message, ToolMessage)
        and message.name in {"aggregate", "find"}
        and message.status != "error"
    )


async def _investigate_with_data_agent(
    incident_context: str, service_name: str | None, config: RunnableConfig
) -> str:
    """Run the Data Intelligence subagent with the live read-only MongoDB MCP tools.

    The agent writes its own query. The application then classifies the dataset (synthetic or
    not) from what the agent actually read, never from what the model claims.
    """
    settings = get_settings()
    task = _task(
        incident_context,
        service_name,
        settings.mongodb_mcp_database,
        settings.mongodb_mcp_events_collection,
    )
    async with MongoDBMCPClient(
        settings.mongodb_mcp_url, settings.mongodb_mcp_connection_string
    ).read_tools() as tool_set:
        agent = build_data_intelligence_agent(tool_set.read_tools)
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=task)]}, config=subagent_config(config)
        )
    finding = result.get("structured_response")
    if finding is None:
        return DataIntelligenceFinding(
            summary="The Data Intelligence agent stopped before writing its finding.",
            limitations=["The agent reached its call limit without a finding."],
            confidence=0,
        ).model_dump_json()
    events = _read_results(result.get("messages", []))
    classified = _classify_dataset(
        DataIntelligenceFinding.model_validate(finding), is_synthetic=_is_synthetic_dataset(events)
    )
    return classified.model_dump_json()


@tool(
    "ask_data_intelligence",
    description=(
        "Analyse read-only MongoDB operational events of one service. Use for timelines, error "
        "signatures, and evidence-based technical hypotheses. Pass service_name when the "
        "request names a service."
    ),
)
async def ask_data_intelligence(
    incident_context: str, config: RunnableConfig, service_name: str | None = None
) -> str:
    """Delegate an incident question to the read-only Data Intelligence specialist."""
    settings = get_settings()
    if settings.mongodb_mcp_enabled:
        try:
            finding_json = await _investigate_with_data_agent(incident_context, service_name, config)
            return finding_json
        except Exception:
            logger.exception("MongoDB specialist delegation failed")
            return DataIntelligenceFinding(
                summary="Live MongoDB MCP was unavailable during this investigation.",
                timeline=[],
                error_signatures=[],
                evidence=[],
                suspected_root_causes=[],
                confidence=0,
            ).model_dump_json()

    return DataIntelligenceFinding(
        summary="Live MongoDB MCP is unavailable because MONGODB_MCP_ENABLED is false.",
        timeline=[],
        error_signatures=[],
        evidence=[],
        suspected_root_causes=[],
        confidence=0,
    ).model_dump_json()
