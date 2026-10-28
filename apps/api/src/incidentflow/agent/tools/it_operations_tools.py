"""Supervisor tool for read-only Jira incident investigation."""

import logging
from uuid import uuid4

from langchain.tools import tool

from incidentflow.agent.agents_specialist.contracts import ITOperationsFinding
from incidentflow.agent.agents_specialist.it_operations import build_it_operations_agent
from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings

logger = logging.getLogger(__name__)


async def _investigate_incident_with_jira(incident_context: str) -> str:
    """Ask the Jira specialist to find ticket evidence related to an incident.

    The specialist can only use the read-only Jira tools exposed by the MCP client.
    """
    settings = get_settings()
    async with JiraMCPClient(settings.jira_mcp_url).read_tools() as tool_set:
        agent = build_it_operations_agent(jira_tools=tool_set.read_tools)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": incident_context}]},
            config={
                "recursion_limit": 12,
                "configurable": {"thread_id": f"it-operations:{uuid4()}"},
            },
        )
        return result["structured_response"].model_dump_json()


@tool(
    "ask_it_operations",
    description="Retrieve read-only Jira incident context and related ticket evidence. Use for ticket history and operational hypotheses.",
)
async def ask_it_operations(incident_context: str) -> str:
    """Delegate an incident question to the read-only IT Operations specialist."""
    settings = get_settings()
    if settings.jira_mcp_enabled:
        try:
            finding_json = await _investigate_incident_with_jira(incident_context)
            return finding_json
        except Exception:
            logger.exception("Jira specialist delegation failed")
            return ITOperationsFinding(
                summary="Live Jira MCP was unavailable during this investigation.",
                related_ticket_ids=[],
                evidence=[],
                hypotheses=[],
                confidence=0,
            ).model_dump_json()

    return ITOperationsFinding(
        summary="Live Jira MCP is unavailable because JIRA_MCP_ENABLED is false.",
        related_ticket_ids=[],
        evidence=[],
        hypotheses=[],
        confidence=0,
    ).model_dump_json()
