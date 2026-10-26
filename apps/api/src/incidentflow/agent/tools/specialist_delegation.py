import logging
from uuid import uuid4

from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from incidentflow.agent.agents_specialist.contracts import (
    DataIntelligenceFinding,
    GitHubFinding,
    ITOperationsFinding,
    KnowledgeFinding,
)
from incidentflow.agent.agents_specialist.data_intelligence import (
    build_data_intelligence_agent,
)
from incidentflow.agent.agents_specialist.github import build_github_analysis_model
from incidentflow.agent.agents_specialist.it_operations import (
    build_it_operations_agent,
)
from incidentflow.agent.agents_specialist.knowledge import build_knowledge_agent
from incidentflow.agent.mcp_clients.github import GitHubMCPClient
from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.agent.mcp_clients.mongodb import MongoDBMCPClient
from incidentflow.agent.prompts.github import GITHUB_ANALYSIS_SYSTEM_PROMPT
from incidentflow.core.config import get_settings

logger = logging.getLogger(__name__)


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
        evidence_blocks: list[str] = []
        for repository in settings.github_mcp_allowed_repositories:
            owner, repo = repository.split("/", maxsplit=1)
            for tool_name in ("list_commits", "list_pull_requests"):
                try:
                    result = await tool_set.get(tool_name).ainvoke({"owner": owner, "repo": repo})
                    content = getattr(result, "content", result)
                    evidence_blocks.append(
                        f"{tool_name} for {repository}:\n{str(content)[:6000]}"
                    )
                except Exception as error:  # noqa: BLE001 - preserve partial MCP evidence.
                    logger.warning("GitHub MCP read failed for %s in %s", tool_name, repository)
                    evidence_blocks.append(
                        f"{tool_name} for {repository} failed: {type(error).__name__}."
                    )

    analyzer = build_github_analysis_model()
    finding = await analyzer.ainvoke(
        [
            SystemMessage(content=GITHUB_ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Incident context:\n{incident_context}\n\n"
                    "GitHub evidence collected by the application:\n"
                    + "\n\n".join(evidence_blocks)
                )
            ),
        ]
    )
    return finding.model_dump_json()


@tool
async def ask_it_operations(incident_context: str) -> str:
    """Investigate related incident tickets and operational history.

    Use for historical Jira context, related ticket identifiers, and operational
    hypotheses. This delegates only the supplied incident context to the read-only
    IT Operations Agent when Jira MCP has been deliberately enabled.
    """
    settings = get_settings()
    if settings.jira_mcp_enabled:
        try:
            return await _run_real_it_operations(incident_context)
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


@tool
async def ask_data_intelligence(incident_context: str) -> str:
    """Investigate technical events, logs, and possible root causes.

    Use for error signatures and technical timelines. This delegates only the
    supplied incident context to the read-only Data Intelligence Agent when
    MongoDB MCP has been deliberately enabled.
    """
    settings = get_settings()
    if settings.mongodb_mcp_enabled:
        try:
            return await _run_real_data_intelligence(incident_context)
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


@tool
async def ask_github(incident_context: str) -> str:
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
        try:
            return await _run_real_github(incident_context)
        except Exception:
            logger.exception("GitHub specialist delegation failed")
            return GitHubFinding(
                summary="Live GitHub MCP was unavailable during this investigation.",
                repository=", ".join(settings.github_mcp_allowed_repositories),
                related_pull_requests=[],
                related_commits=[],
                evidence=[],
                hypotheses=[],
                limitations=[
                    "No live GitHub evidence was collected because the GitHub MCP connection failed."
                ],
                confidence=0,
            ).model_dump_json()

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
        personal_access_token=settings.github_personal_access_token,
    )


@tool
def ask_knowledge(incident_context: str) -> str:
    """Retrieve relevant incident response guides and grounded troubleshooting guidance.

    Use for internal-documentation context and source-attributed recommendations.
    This delegates only the supplied incident context to the read-only Knowledge Agent.
    """
    try:
        agent = build_knowledge_agent()
        result = agent.invoke(
            {"messages": [{"role": "user", "content": incident_context}]},
            config={"recursion_limit": 6},
        )
        return result["structured_response"].model_dump_json()
    except Exception:
        logger.exception("Knowledge specialist delegation failed")
        return KnowledgeFinding(
            summary="Knowledge retrieval was unavailable during this investigation.",
            relevant_documents=[],
            evidence=[],
            recommended_steps=[],
            limitations=["No Pinecone evidence was collected because retrieval failed."],
            confidence=0,
        ).model_dump_json()
