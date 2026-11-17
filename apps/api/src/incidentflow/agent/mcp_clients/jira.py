"""Least-privilege client for the official Jira Cloud MCP server.

Tool schemas are normalised for OpenAI strict mode, which rejects required names whose
properties were removed.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from fastmcp.client.auth import OAuth
from key_value.aio.protocols.key_value import AsyncKeyValue
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool, StructuredTool

from incidentflow.agent.mcp_clients.oauth_store import (
    NonInteractiveOAuth,
    RefreshingOAuth,
    build_oauth_token_storage,
    close_oauth_token_storage,
)

JIRA_OAUTH_CALLBACK_PORT = 8765

JIRA_READ_TOOL_NAMES = (
    "getAccessibleAtlassianResources",
    "listJiraProjects",
    "listJiraProjectIssueTypesMetadata",
    "searchJiraIssuesUsingJql",
    "getJiraIssue",
)
JIRA_WRITE_TOOL_NAMES = (
    "createJiraIssue",
    "addOrEditJiraIssueComment",
)
JIRA_OPTIONAL_WRITE_FIELDS = frozenset({"assignee", "parent", "assignToSprint"})
JIRA_TOOL_DESCRIPTIONS = {
    "getAccessibleAtlassianResources": "List the accessible Atlassian cloud resources.",
    "listJiraProjects": "List the Jira projects available in one cloud resource.",
    "listJiraProjectIssueTypesMetadata": "List valid issue types for one Jira project.",
    "searchJiraIssuesUsingJql": "Search Jira issues with a supplied JQL query.",
    "getJiraIssue": "Read one Jira issue by its key or ID.",
    "createJiraIssue": "Create one Jira issue after explicit human approval.",
    "addOrEditJiraIssueComment": "Add or edit a Jira issue comment after explicit approval.",
}


@dataclass(frozen=True)
class JiraMCPToolSet:
    """The deliberately small set of Jira operations IncidentFlow can use."""

    read_tools: list[BaseTool]
    write_tools: list[BaseTool]

    def get(self, name: str) -> BaseTool:
        """Return the allowlisted Jira read and write tools."""
        for tool in (*self.read_tools, *self.write_tools):
            if tool.name == name:
                return tool
        raise KeyError(f"Jira MCP tool is not approved: {name}")


class JiraMCPClient:
    """Discover and restrict Jira Cloud MCP tools to approved operations only."""

    def __init__(self, server_url: str, *, interactive: bool | None = None) -> None:
        self.server_url = server_url
        self.interactive = interactive

    @asynccontextmanager
    async def _adapter(self) -> AsyncIterator[MCPAdapter]:
        """Connect to Jira MCP and always release the token store's connection afterwards."""
        from incidentflow.core.config import get_settings

        token_storage = build_oauth_token_storage(get_settings())
        try:
            client = Client(self.server_url, auth=self._oauth_auth(token_storage))
            async with MCPAdapter(client) as adapter:
                yield adapter
        finally:
            await close_oauth_token_storage(token_storage)

    def _oauth_auth(self, token_storage: AsyncKeyValue | None) -> str | OAuth:
        """Use the encrypted store when configured; only interactive runs may open a browser."""
        from incidentflow.core.config import get_settings

        if token_storage is None:
            return "oauth"
        interactive = self.interactive
        if interactive is None:
            interactive = get_settings().mcp_oauth_interactive
        if interactive:
            return RefreshingOAuth(
                mcp_url=self.server_url,
                client_name="IncidentFlow Jira MCP",
                token_storage=token_storage,
                callback_port=JIRA_OAUTH_CALLBACK_PORT,
            )
        return NonInteractiveOAuth(
            mcp_url=self.server_url,
            client_name="IncidentFlow Jira MCP",
            token_storage=token_storage,
        )

    @asynccontextmanager
    async def read_tools(self) -> AsyncIterator[JiraMCPToolSet]:
        """Keep the MCP connection alive while approved read tools are invoked."""
        async with self._adapter() as adapter:
            yield select_read_tools(await adapter.list_tools())

    @asynccontextmanager
    async def ticket_tools(self) -> AsyncIterator[JiraMCPToolSet]:
        """Keep the MCP connection alive while approved ticket writes are invoked."""
        async with self._adapter() as adapter:
            yield select_ticket_tools(await adapter.list_tools())

    async def list_tools(self) -> list[BaseTool]:
        """Discover tool metadata without returning tools intended for later use."""
        async with self._adapter() as adapter:
            return await adapter.list_tools()


def select_read_tools(tools: Sequence[BaseTool]) -> JiraMCPToolSet:
    """Select only the approved read operations from the server catalog."""
    tools_by_name = {tool.name: tool for tool in tools}
    missing_tools = [name for name in JIRA_READ_TOOL_NAMES if name not in tools_by_name]
    if missing_tools:
        missing_names = ", ".join(missing_tools)
        raise RuntimeError(f"Jira MCP server is missing required read tools: {missing_names}")

    return JiraMCPToolSet(
        read_tools=[_approve_tool(tools_by_name[name]) for name in JIRA_READ_TOOL_NAMES],
        write_tools=[],
    )


def select_ticket_tools(tools: Sequence[BaseTool]) -> JiraMCPToolSet:
    """Select the read prerequisites plus the two approved ticket write operations."""
    read_tool_set = select_read_tools(tools)
    tools_by_name = {tool.name: tool for tool in tools}
    missing_tools = [name for name in JIRA_WRITE_TOOL_NAMES if name not in tools_by_name]
    if missing_tools:
        missing_names = ", ".join(missing_tools)
        raise RuntimeError(
            f"Jira MCP server is missing required ticket write tools: {missing_names}"
        )

    return JiraMCPToolSet(
        read_tools=read_tool_set.read_tools,
        write_tools=[
            _prepare_ticket_write_tool(tools_by_name[name]) for name in JIRA_WRITE_TOOL_NAMES
        ],
    )


def _approve_tool(tool: BaseTool) -> BaseTool:
    """Keep remote execution while adapting its metadata to our bounded contract."""
    tool.description = JIRA_TOOL_DESCRIPTIONS[tool.name]
    tool.args_schema = _openai_compatible_schema(tool.args_schema)
    return tool


def _prepare_ticket_write_tool(tool: BaseTool) -> BaseTool:
    """Wrap one approved Jira write so blank optional values never reach Jira."""
    approved_tool = _approve_tool(tool)

    async def invoke_ticket_write(**arguments: Any) -> Any:
        """Forward the approved arguments after removing empty optional fields."""
        sanitized_arguments = _without_empty_optional_jira_fields(arguments)
        return await approved_tool.ainvoke(sanitized_arguments)

    return StructuredTool(
        name=approved_tool.name,
        description=approved_tool.description,
        args_schema=approved_tool.args_schema,
        coroutine=invoke_ticket_write,
    )


def _without_empty_optional_jira_fields(arguments: dict[str, Any]) -> dict[str, Any]:
    """Omit optional Jira fields when strict tool calling supplied an empty string."""
    return {
        name: value
        for name, value in arguments.items()
        if name not in JIRA_OPTIONAL_WRITE_FIELDS or value != ""
    }


def _openai_compatible_schema(schema: object) -> object:
    """Drop MCP inputs that cannot satisfy OpenAI strict tool-schema rules."""
    if isinstance(schema, dict):
        normalized = deepcopy(schema)
    elif isinstance(schema, type) and hasattr(schema, "model_json_schema"):
        normalized = schema.model_json_schema()
    else:
        return schema

    properties = normalized.get("properties")
    if isinstance(properties, dict):
        for name, property_schema in tuple(properties.items()):
            if _contains_untyped_array_items(property_schema) or _contains_open_object(
                property_schema
            ):
                properties.pop(name)

    if isinstance(properties, dict):
        normalized["required"] = list(properties)
    return normalized


def _contains_untyped_array_items(schema: object) -> bool:
    """Return whether any array item schema lacks a concrete JSON Schema type."""
    if not isinstance(schema, dict):
        return False

    items = schema.get("items")
    if isinstance(items, dict) and "type" not in items:
        return True

    return any(_contains_untyped_array_items(value) for value in schema.values())


def _contains_open_object(schema: object) -> bool:
    """Return whether a nested object accepts arbitrary keys, which strict tools forbid."""
    if not isinstance(schema, dict):
        return False

    if schema.get("type") == "object" and schema.get("additionalProperties") is not False:
        return True

    return any(_contains_open_object(value) for value in schema.values())
