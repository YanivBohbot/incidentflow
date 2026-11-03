"""ask_github: the Supervisor delegates to the GitHub Agent (a create_agent).

The agent chooses its GitHub reads (commits, pull requests, code search) itself. Its middleware
keeps every call inside the allowlisted repositories, truncates large results, and bounds the
loop. It returns a validated GitHubFinding.
"""

import logging
from datetime import UTC, datetime, timedelta

from langchain.tools import tool
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from incidentflow.agent.agents_specialist.github import build_github_agent
from incidentflow.agent.findings import GitHubFinding
from incidentflow.agent.mcp_clients.github import GitHubMCPClient
from incidentflow.agent.tools.subagent_runtime import subagent_config
from incidentflow.core.config import get_settings

logger = logging.getLogger(__name__)


def _task(
    incident_context: str,
    repositories: tuple[str, ...],
    branch: str | None = None,
    lookback_days: int = 14,
) -> str:
    """The delegation message: the incident, the readable repositories, and the time window.

    The model does not know today's date, so the application gives the window explicitly.
    """
    since = (datetime.now(UTC) - timedelta(days=lookback_days)).replace(microsecond=0)
    targets = "; ".join(
        f"{repository} (owner={repository.split('/')[0]}, repo={repository.split('/', 1)[1]})"
        for repository in repositories
    )
    return (
        f"Incident context:\n{incident_context}\n\n"
        f"Allowed repositories: {targets}\n"
        f"Today (UTC): {datetime.now(UTC).date().isoformat()}. "
        f"Look at changes since {since.isoformat()} (pass since=... to list_commits).\n"
        "search_code must put the repository in the query, for example: "
        f"'<terms> repo:{repositories[0]}'."
        + (
            f"\nRead branch {branch}: pass sha={branch} to list_commits, and base={branch} "
            "with state=all to list_pull_requests. Code search only covers the default branch."
            if branch
            else ""
        )
    )


async def _investigate_with_github_agent(incident_context: str, config: RunnableConfig) -> str:
    """Run the GitHub subagent with the live read-only MCP tools."""
    settings = get_settings()
    if not settings.github_mcp_is_configured:
        raise RuntimeError("GitHub MCP transport must be configured when GitHub MCP is enabled.")
    repositories = settings.github_mcp_allowed_repositories
    async with _create_github_mcp_client().read_tools() as tool_set:
        agent = build_github_agent(tool_set.read_tools)
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=_task(incident_context, repositories, settings.github_mcp_branch))]},
            config=subagent_config(config),
        )
    finding = result.get("structured_response")
    if finding is None:
        return GitHubFinding(
            summary="The GitHub agent stopped before writing its finding.",
            repository=", ".join(repositories),
            limitations=["The GitHub agent reached its call limit without a finding."],
            confidence=0,
        ).model_dump_json()
    return GitHubFinding.model_validate(finding).model_dump_json()


def _create_github_mcp_client() -> GitHubMCPClient:
    """Create the configured read-only connection to the GitHub MCP server.

    HTTP targets GitHub's remote MCP server with the personal access token (works from the
    API container). stdio runs the server locally with `docker run` (works on a host that
    has Docker).
    """
    settings = get_settings()
    if settings.github_mcp_transport == "http":
        return GitHubMCPClient(
            server_url=settings.github_mcp_url,
            personal_access_token=settings.github_personal_access_token,
        )
    return GitHubMCPClient(
        command=settings.github_mcp_command,
        command_args=settings.github_mcp_stdio_arguments,
        personal_access_token=settings.github_personal_access_token,
    )


@tool(
    "ask_github",
    description="Inspect read-only GitHub commits and pull requests in allowed repositories. Use for code-change evidence relevant to an incident.",
)
async def ask_github(incident_context: str, config: RunnableConfig) -> str:
    """Delegate an incident question to the read-only GitHub specialist."""
    settings = get_settings()
    if settings.github_mcp_enabled and settings.github_mcp_is_configured and settings.github_mcp_allowed_repositories:
        try:
            finding_json = await _investigate_with_github_agent(incident_context, config)
            return finding_json
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
