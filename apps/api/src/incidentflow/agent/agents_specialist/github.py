import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from incidentflow.agent.agents_specialist.contracts import GitHubFinding
from incidentflow.agent.identities import GITHUB_AGENT
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.github import GITHUB_SYSTEM_PROMPT
from incidentflow.core.config import get_settings

ToolResult = ToolMessage | Command[Any]
_REPOSITORY_QUALIFIER = re.compile(r"(?:^|\s)repo:([^\s]+)")


def validate_github_repository_arguments(
    tool_name: str, arguments: dict[str, Any], allowed_repositories: tuple[str, ...]
) -> str | None:
    """Reject GitHub calls outside the configured repository allowlist before MCP execution."""
    allowed = {repository.casefold() for repository in allowed_repositories}
    if tool_name == "search_code":
        query = str(arguments.get("query", ""))
        repositories = _REPOSITORY_QUALIFIER.findall(query)
        if not repositories:
            return "GitHub code search requires a repo:owner/repository qualifier from the allowlist."
        if " OR " in query.upper() or "org:" in query.casefold() or "user:" in query.casefold():
            return "GitHub code search may only target explicit allowlisted repo qualifiers."
        if any(repository.casefold() not in allowed for repository in repositories):
            return "GitHub code search requested a repository outside the allowlist."
        return None

    owner = arguments.get("owner")
    repository = arguments.get("repo")
    if not isinstance(owner, str) or not isinstance(repository, str):
        return "GitHub read tools require owner and repo from the configured allowlist."
    if f"{owner}/{repository}".casefold() not in allowed:
        return "GitHub tool requested a repository outside the allowlist."
    return None


class GitHubRepositoryAllowlistMiddleware(AgentMiddleware):
    """Prevent the model from sending a GitHub MCP call to an unapproved repository."""

    def __init__(self, allowed_repositories: tuple[str, ...]) -> None:
        self.allowed_repositories = allowed_repositories

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        error = validate_github_repository_arguments(
            request.tool_call["name"], request.tool_call["args"], self.allowed_repositories
        )
        if error:
            return ToolMessage(
                content=error,
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        error = validate_github_repository_arguments(
            request.tool_call["name"], request.tool_call["args"], self.allowed_repositories
        )
        if error:
            return ToolMessage(
                content=error,
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return await handler(request)


def build_github_middleware(allowed_repositories: tuple[str, ...]) -> list[AgentMiddleware]:
    """Bound GitHub reads so an investigation stays focused and inexpensive."""
    return [
        *build_shared_middleware(),
        GitHubRepositoryAllowlistMiddleware(allowed_repositories),
        *[
            ToolCallLimitMiddleware(tool_name=tool_name, run_limit=1, exit_behavior="end")
            for tool_name in (
                "list_commits",
                "list_pull_requests",
                "search_code",
            )
        ],
        ToolCallLimitMiddleware(tool_name="pull_request_read", run_limit=2, exit_behavior="end"),
    ]


def build_github_agent(github_tools: list[BaseTool]):
    """Build the read-only GitHub specialist with injected live MCP tools."""
    settings = get_settings()
    allowed_repositories = settings.github_mcp_allowed_repositories
    if not allowed_repositories:
        raise RuntimeError("GITHUB_MCP_REPOSITORIES must configure at least one repository.")

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=settings.openai_timeout_seconds,
    )
    return create_agent(
        model=model,
        tools=github_tools,
        system_prompt=GITHUB_SYSTEM_PROMPT.format(
            repositories=", ".join(allowed_repositories)
        ),
        name=GITHUB_AGENT.technical_name,
        middleware=build_github_middleware(allowed_repositories),
        response_format=ToolStrategy(GitHubFinding),
    )
