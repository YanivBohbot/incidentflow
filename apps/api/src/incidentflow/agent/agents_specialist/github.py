import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from incidentflow.agent.findings import GitHubFinding
from incidentflow.agent.identities import GITHUB_AGENT
from incidentflow.agent.middleware import TruncateToolOutputMiddleware, build_shared_middleware
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


def with_branch_defaults(
    tool_name: str, arguments: dict[str, Any], branch: str | None
) -> dict[str, Any]:
    """Target the configured branch when the model leaves the branch argument out."""
    if not branch:
        return arguments
    if tool_name == "list_commits" and not arguments.get("sha"):
        return {**arguments, "sha": branch}
    if tool_name == "list_pull_requests" and not arguments.get("base"):
        return {**arguments, "base": branch, "state": arguments.get("state") or "all"}
    return arguments


class GitHubRepositoryAllowlistMiddleware(AgentMiddleware):
    """Keep every GitHub MCP call inside the allowlisted repositories (and branch).

    A call to another repository is rejected before it reaches GitHub. When a branch is
    configured, the application, not the model, makes commit and pull-request reads target it.
    """

    def __init__(self, allowed_repositories: tuple[str, ...], branch: str | None = None) -> None:
        self.allowed_repositories = allowed_repositories
        self.branch = branch

    def _prepare(self, request: ToolCallRequest) -> ToolCallRequest | ToolMessage:
        call = request.tool_call
        error = validate_github_repository_arguments(
            call["name"], call["args"], self.allowed_repositories
        )
        if error:
            return ToolMessage(content=error, tool_call_id=call["id"], status="error")
        arguments = with_branch_defaults(call["name"], call["args"], self.branch)
        if arguments is call["args"]:
            return request
        return request.override(tool_call={**call, "args": arguments})

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        prepared = self._prepare(request)
        return prepared if isinstance(prepared, ToolMessage) else handler(prepared)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        prepared = self._prepare(request)
        return prepared if isinstance(prepared, ToolMessage) else await handler(prepared)


def build_github_middleware(
    allowed_repositories: tuple[str, ...], branch: str | None = None
) -> list[AgentMiddleware[Any, Any, Any]]:
    """Bound GitHub reads and model turns so an investigation cannot loop."""
    return [
        *build_shared_middleware(),
        GitHubRepositoryAllowlistMiddleware(allowed_repositories, branch),
        TruncateToolOutputMiddleware(max_characters=6000),
        # Per-tool limits only (1 + 1 + 1 + 2 = at most five reads). Do not add a global
        # ToolCallLimitMiddleware as well: when both block the same call, each adds its own
        # ToolMessage for one tool_call_id, and OpenAI rejects the conversation.
        *[
            ToolCallLimitMiddleware(tool_name=tool_name, run_limit=1, exit_behavior="continue")
            for tool_name in (
                "list_commits",
                "list_pull_requests",
                "search_code",
            )
        ],
        ToolCallLimitMiddleware(
            tool_name="pull_request_read", run_limit=2, exit_behavior="continue"
        ),
        # Reads in parallel, one or two follow-up reads, then GitHubFinding, plus room for
        # one corrective turn. Live runs showed fewer turns could end the agent before it
        # wrote its finding.
        ModelCallLimitMiddleware(run_limit=6, exit_behavior="end"),
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
        middleware=build_github_middleware(allowed_repositories, settings.github_mcp_branch),
        response_format=ToolStrategy(GitHubFinding),
    )

