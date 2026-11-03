"""Supervisor tool for Jira investigation and approval-gated Jira writes."""

import logging

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt

from incidentflow.agent.agents_specialist.it_operations import build_it_operations_agent
from incidentflow.agent.findings import ITOperationsFinding
from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.agent.tools.subagent_runtime import subagent_config
from incidentflow.core.config import get_settings

logger = logging.getLogger(__name__)


async def _investigate_incident_with_jira(
    incident_context: str,
    config: RunnableConfig,
) -> str:
    """Ask the Jira specialist to investigate or perform an approved Jira write.

    The specialist chooses from the bounded Jira catalog. LangChain pauses before
    either approved write tool executes.
    """
    settings = get_settings()
    client = JiraMCPClient(settings.jira_mcp_url)
    tool_context = client.ticket_tools() if settings.jira_mcp_write_enabled else client.read_tools()
    async with tool_context as tool_set:
        agent = build_it_operations_agent(jira_tools=[*tool_set.read_tools, *tool_set.write_tools])
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": incident_context}]},
            config=subagent_config(config),
        )
        return result["structured_response"].model_dump_json()


def with_operator_request(incident_context: str, config: RunnableConfig | None) -> str:
    """Put the operator's own words in front of the supervisor's summary.

    A Jira write must be requested explicitly by the operator. The supervisor may paraphrase
    or drop that request, so the application forwards the original request itself.
    """
    original = ((config or {}).get("configurable") or {}).get("incident_request")
    if not original or original in incident_context:
        return incident_context
    return (
        f"Operator request (verbatim):\n{original}\n\nSupervisor context:\n{incident_context}"
    )


@tool(
    "ask_it_operations",
    description=(
        "Investigate Jira incident context, or create an issue/comment only when the request "
        "explicitly asks for that Jira write. Every Jira write pauses for human approval."
    ),
)
async def ask_it_operations(incident_context: str, config: RunnableConfig) -> str:
    """Delegate Jira work while preserving the parent graph's durable runtime context."""
    incident_context = with_operator_request(incident_context, config)
    settings = get_settings()
    if settings.jira_mcp_enabled:
        try:
            finding_json = await _investigate_incident_with_jira(incident_context, config)
            return finding_json
        except GraphInterrupt:
            # Let LangGraph persist and bubble a pending Jira tool approval.
            raise
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
