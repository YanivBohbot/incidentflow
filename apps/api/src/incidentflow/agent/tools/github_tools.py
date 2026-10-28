"""Supervisor tool for read-only GitHub change analysis."""

import logging

from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from incidentflow.agent.agents_specialist.contracts import GitHubFinding
from incidentflow.agent.agents_specialist.github import build_github_analysis_model
from incidentflow.agent.mcp_clients.github import GitHubMCPClient
from incidentflow.agent.prompts.github import GITHUB_ANALYSIS_SYSTEM_PROMPT
from incidentflow.core.config import get_settings

logger = logging.getLogger(__name__)


async def _analyse_incident_related_github_changes(incident_context: str) -> str:
    """Collect allowed GitHub changes, then relate them to the incident context.

    The application fetches commits and pull requests before the model writes its finding.
    """
    settings = get_settings()
    if not settings.github_mcp_is_configured:
        raise RuntimeError("GitHub MCP transport must be configured when GitHub MCP is enabled.")

    async with _create_github_mcp_client().read_tools() as tool_set:
        evidence_blocks: list[str] = []
        for repository in settings.github_mcp_allowed_repositories:
            owner, repo = repository.split("/", maxsplit=1)
            for tool_name in ("list_commits", "list_pull_requests"):
                try:
                    result = await tool_set.get(tool_name).ainvoke({"owner": owner, "repo": repo})
                    content = getattr(result, "content", result)
                    evidence_blocks.append(f"{tool_name} for {repository}:\n{str(content)[:6000]}")
                except Exception as error:  # noqa: BLE001 - preserve partial MCP evidence.
                    logger.warning("GitHub MCP read failed for %s in %s", tool_name, repository)
                    evidence_blocks.append(f"{tool_name} for {repository} failed: {type(error).__name__}.")

    analyzer = build_github_analysis_model()
    finding = await analyzer.ainvoke(
        [
            SystemMessage(content=GITHUB_ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(content=f"Incident context:\n{incident_context}\n\nGitHub evidence collected by the application:\n" + "\n\n".join(evidence_blocks)),
        ]
    )
    return finding.model_dump_json()


def _create_github_mcp_client() -> GitHubMCPClient:
    """Create the configured read-only connection to the GitHub MCP server.

    It supports either an HTTP MCP server or the local Docker-based MCP process.
    """
    settings = get_settings()
    if settings.github_mcp_transport == "http":
        return GitHubMCPClient(server_url=settings.github_mcp_url)
    return GitHubMCPClient(
        command=settings.github_mcp_command,
        command_args=settings.github_mcp_stdio_arguments,
        personal_access_token=settings.github_personal_access_token,
    )


@tool(
    "ask_github",
    description="Inspect read-only GitHub commits and pull requests in allowed repositories. Use for code-change evidence relevant to an incident.",
)
async def ask_github(incident_context: str) -> str:
    """Delegate an incident question to the read-only GitHub specialist."""
    settings = get_settings()
    if settings.github_mcp_enabled and settings.github_mcp_is_configured and settings.github_mcp_allowed_repositories:
        try:
            return await _analyse_incident_related_github_changes(incident_context)
        except Exception:
            logger.exception("GitHub specialist delegation failed")
            return GitHubFinding(
                summary="Live GitHub MCP was unavailable during this investigation.",
                repository=", ".join(settings.github_mcp_allowed_repositories),
                related_pull_requests=[], related_commits=[], evidence=[], hypotheses=[],
                limitations=["No live GitHub evidence was collected because the GitHub MCP connection failed."],
                confidence=0,
            ).model_dump_json()

    return GitHubFinding(
        summary="Live GitHub MCP is unavailable because GitHub MCP is disabled or its transport and allowed repositories are not configured.",
        repository=", ".join(settings.github_mcp_allowed_repositories) or "unconfigured",
        related_pull_requests=[], related_commits=[], evidence=[], hypotheses=[],
        limitations=["No live GitHub MCP evidence was collected."], confidence=0,
    ).model_dump_json()
