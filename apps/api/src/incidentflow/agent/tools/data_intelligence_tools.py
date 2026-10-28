"""Supervisor tool for read-only MongoDB operational investigation."""

import logging
from uuid import uuid4

from langchain.tools import tool

from incidentflow.agent.agents_specialist.contracts import DataIntelligenceFinding
from incidentflow.agent.agents_specialist.data_intelligence import build_data_intelligence_agent
from incidentflow.agent.mcp_clients.mongodb import MongoDBMCPClient
from incidentflow.core.config import get_settings

logger = logging.getLogger(__name__)


async def _investigate_incident_with_mongodb(incident_context: str) -> str:
    """Ask the MongoDB specialist to analyse operational evidence for an incident.

    The specialist receives only the read-only tools exposed by the MCP client.
    """
    settings = get_settings()
    async with MongoDBMCPClient(settings.mongodb_mcp_url).read_tools() as tool_set:
        agent = build_data_intelligence_agent(mongodb_tools=tool_set.read_tools)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": incident_context}]},
            config={
                "recursion_limit": 18,
                "configurable": {"thread_id": f"data-intelligence:{uuid4()}"},
            },
        )
        return result["structured_response"].model_dump_json()


@tool(
    "ask_data_intelligence",
    description="Analyse read-only MongoDB operational events. Use for timelines, error signatures, and evidence-based technical hypotheses.",
)
async def ask_data_intelligence(incident_context: str) -> str:
    """Delegate an incident question to the read-only Data Intelligence specialist."""
    settings = get_settings()
    if settings.mongodb_mcp_enabled:
        try:
            finding_json = await _investigate_incident_with_mongodb(incident_context)
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
