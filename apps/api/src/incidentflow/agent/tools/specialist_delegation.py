import asyncio
from uuid import uuid4

from langchain.tools import tool

from incidentflow.agent.agents_specialist.contracts import (
    DataIntelligenceFinding,
    GitHubFinding,
    ITOperationsFinding,
)
from incidentflow.agent.agents_specialist.data_intelligence import (
    build_data_intelligence_agent,
)
from incidentflow.agent.agents_specialist.github import build_github_agent
from incidentflow.agent.agents_specialist.it_operations import (
    build_it_operations_agent,
)
from incidentflow.agent.agents_specialist.knowledge import build_knowledge_agent
from incidentflow.agent.mcp_clients.github import GitHubMCPClient
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


async def _run_real_github(incident_context: str) -> str:
    settings = get_settings()
    if not settings.github_mcp_is_configured:
        raise RuntimeError("GitHub MCP transport must be configured when GitHub MCP is enabled.")

    async with _github_mcp_client().read_tools() as tool_set:
        agent = build_github_agent(github_tools=tool_set.read_tools)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": incident_context}]},
            config={
                "recursion_limit": 14,
                "configurable": {"thread_id": f"github:{uuid4()}"},
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
def ask_github(incident_context: str) -> str:
    """Inspect relevant recent GitHub commits and pull requests without modifying GitHub.

    Use for source-control context, code-change evidence, commit identifiers, and
    pull requests potentially correlated with the incident. This delegates only
    the supplied incident context to the read-only GitHub Agent when GitHub MCP
    has been deliberately enabled and at least one allowed repository is configured.
    """
    settings = get_settings()
    if (
        settings.github_mcp_enabled
        and settings.github_mcp_is_configured
        and settings.github_mcp_allowed_repositories
    ):
        return asyncio.run(_run_real_github(incident_context))

    return GitHubFinding(
        summary=(
            "Live GitHub MCP is unavailable because GitHub MCP is disabled or its transport and "
            "allowed repositories are not configured."
        ),
        repository=", ".join(settings.github_mcp_allowed_repositories) or "unconfigured",
        related_pull_requests=[],
        related_commits=[],
        evidence=[],
        hypotheses=[],
        limitations=["No live GitHub MCP evidence was collected."],
        confidence=0,
    ).model_dump_json()


def _github_mcp_client() -> GitHubMCPClient:
    settings = get_settings()
    if settings.github_mcp_transport == "http":
        return GitHubMCPClient(server_url=settings.github_mcp_url)
    return GitHubMCPClient(
        command=settings.github_mcp_command,
        command_args=settings.github_mcp_stdio_arguments,
    )


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
