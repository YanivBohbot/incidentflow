"""Least-privilege client for a GitHub MCP server."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
import os

from fastmcp import Client
from fastmcp.client import StdioTransport
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

GITHUB_READ_TOOL_NAMES = (
    "list_commits",
    "list_pull_requests",
    "pull_request_read",
    "search_code",
)
GITHUB_TOOL_DESCRIPTIONS = {
    "list_commits": "Read a bounded, recent list of commits from the configured repository.",
    "list_pull_requests": "Read pull requests from the configured repository.",
    "pull_request_read": (
        "Read one pull request's metadata or changed files using only its get or get_files method."
    ),
    "search_code": "Search read-only code references for an incident identifier or service name.",
}


@dataclass(frozen=True)
class GitHubMCPToolSet:
    """The deliberately small GitHub MCP surface available to IncidentFlow."""

    read_tools: list[BaseTool]

    def get(self, name: str) -> BaseTool:
        for mcp_tool in self.read_tools:
            if mcp_tool.name == name:
                return mcp_tool
        raise KeyError(f"GitHub MCP tool is not approved: {name}")


class GitHubMCPClient:
    """Discover and restrict GitHub MCP tools to investigation-only reads."""

    def __init__(
        self,
        server_url: str | None = None,
        *,
        command: str | None = None,
        command_args: tuple[str, ...] = (),
        personal_access_token: str | None = None,
    ) -> None:
        if not server_url and not command:
            raise ValueError("GitHub MCP requires either an HTTP URL or a stdio command.")
        self.server_url = server_url
        self.command = command
        self.command_args = command_args
        self.personal_access_token = personal_access_token

    def _client(self) -> Client:
        if self.command:
            command_args = list(self.command_args)
            environment = None
            if self.personal_access_token:
                image_position = next(
                    (
                        index
                        for index, argument in enumerate(command_args)
                        if argument.startswith("ghcr.io/github/github-mcp-server")
                    ),
                    len(command_args),
                )
                command_args[image_position:image_position] = (
                    "-e",
                    "GITHUB_PERSONAL_ACCESS_TOKEN",
                )
                environment = os.environ.copy()
                environment["GITHUB_PERSONAL_ACCESS_TOKEN"] = self.personal_access_token
            return Client(StdioTransport(self.command, command_args, env=environment))
        if self.server_url:
            return Client(self.server_url, auth="oauth")
        raise RuntimeError("GitHub MCP client has no configured transport.")

    @asynccontextmanager
    async def read_tools(self) -> AsyncIterator[GitHubMCPToolSet]:
        """Keep the MCP connection alive while approved read tools are invoked."""
        async with MCPAdapter(self._client()) as adapter:
            yield select_read_tools(await adapter.list_tools())

    async def list_tools(self) -> list[BaseTool]:
        """Discover tool metadata without returning tools intended for later use."""
        async with MCPAdapter(self._client()) as adapter:
            return await adapter.list_tools()


def select_read_tools(tools: Sequence[BaseTool]) -> GitHubMCPToolSet:
    """Select only the approved GitHub operations from the server catalog."""
    tools_by_name = {tool.name: tool for tool in tools}
    missing_tools = [name for name in GITHUB_READ_TOOL_NAMES if name not in tools_by_name]
    if missing_tools:
        missing_names = ", ".join(missing_tools)
        raise RuntimeError(f"GitHub MCP server is missing required read tools: {missing_names}")

    approved_tools = []
    for name in GITHUB_READ_TOOL_NAMES:
        tool = tools_by_name[name]
        tool.description = GITHUB_TOOL_DESCRIPTIONS[name]
        tool.args_schema = _openai_compatible_schema(tool.args_schema)
        approved_tools.append(tool)
    return GitHubMCPToolSet(read_tools=approved_tools)


def _openai_compatible_schema(schema: object) -> object:
    """Strip dynamic JSON Schema constraints unsupported by OpenAI function calling."""
    if isinstance(schema, dict):
        normalized = deepcopy(schema)
    elif isinstance(schema, type) and hasattr(schema, "model_json_schema"):
        normalized = schema.model_json_schema()
    else:
        return schema

    _remove_property_names(normalized)
    return normalized


def _remove_property_names(value: object) -> None:
    if isinstance(value, dict):
        value.pop("propertyNames", None)
        for nested_value in value.values():
            _remove_property_names(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _remove_property_names(nested_value)
