import asyncio
from uuid import uuid4

from langchain.tools import tool

from incidentflow.agent.agents_specialist.contracts import (
    DataIntelligenceFinding,
    ITOperationsFinding,
)
from incidentflow.agent.agents_specialist.data_intelligence import (
    build_data_intelligence_agent,
)
from incidentflow.agent.agents_specialist.it_operations import (
    build_it_operations_agent,
)
from incidentflow.agent.agents_specialist.knowledge import build_knowledge_agent
from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.agent.mcp_clients.mongodb import MongoDBMCPClient
from incidentflow.core.config import get_settings


async def _run_real_it_operations(incident_context: str) -> str:
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


async def _run_real_data_intelligence(incident_context: str) -> str:
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


@tool
def ask_it_operations(incident_context: str) -> str:
    """Investigate related incident tickets and operational history.

    Use for historical Jira context, related ticket identifiers, and operational
    hypotheses. This delegates only the supplied incident context to the read-only
    IT Operations Agent when Jira MCP has been deliberately enabled.
    """
    settings = get_settings()
    if settings.jira_mcp_enabled:
        return asyncio.run(_run_real_it_operations(incident_context))

    return ITOperationsFinding(
        summary="Live Jira MCP is unavailable because JIRA_MCP_ENABLED is false.",
        related_ticket_ids=[],
        evidence=[],
        hypotheses=[],
        confidence=0,
    ).model_dump_json()


@tool
def ask_data_intelligence(incident_context: str) -> str:
    """Investigate technical events, logs, and possible root causes.

    Use for error signatures and technical timelines. This delegates only the
    supplied incident context to the read-only Data Intelligence Agent when
    MongoDB MCP has been deliberately enabled.
    """
    settings = get_settings()
    if settings.mongodb_mcp_enabled:
        return asyncio.run(_run_real_data_intelligence(incident_context))

    return DataIntelligenceFinding(
        summary="Live MongoDB MCP is unavailable because MONGODB_MCP_ENABLED is false.",
        timeline=[],
        error_signatures=[],
        evidence=[],
        suspected_root_causes=[],
        confidence=0,
    ).model_dump_json()


@tool
def ask_knowledge(incident_context: str) -> str:
    """Retrieve relevant incident response guides and grounded troubleshooting guidance.

    Use for internal-documentation context and source-attributed recommendations.
    This delegates only the supplied incident context to the read-only Knowledge Agent.
    """
    agent = build_knowledge_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": incident_context}]},
        config={"recursion_limit": 6},
    )
    return result["structured_response"].model_dump_json()
