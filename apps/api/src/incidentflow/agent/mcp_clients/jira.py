"""Least-privilege client for the official Jira Cloud MCP server."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass

from fastmcp import Client
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

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
        for tool in (*self.read_tools, *self.write_tools):
            if tool.name == name:
                return tool
        raise KeyError(f"Jira MCP tool is not approved: {name}")


class JiraMCPClient:
    """Discover and restrict Jira Cloud MCP tools to approved operations only."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    def _client(self) -> Client:
        return Client(self.server_url, auth="oauth")

    @asynccontextmanager
    async def read_tools(self) -> AsyncIterator[JiraMCPToolSet]:
        """Keep the MCP connection alive while approved read tools are invoked."""
        async with MCPAdapter(self._client()) as adapter:
            yield select_read_tools(await adapter.list_tools())

    @asynccontextmanager
    async def ticket_tools(self) -> AsyncIterator[JiraMCPToolSet]:
        """Keep the MCP connection alive while approved ticket writes are invoked."""
        async with MCPAdapter(self._client()) as adapter:
            yield select_ticket_tools(await adapter.list_tools())

    async def list_tools(self) -> list[BaseTool]:
        """Discover tool metadata without returning tools intended for later use."""
        async with MCPAdapter(self._client()) as adapter:
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
        write_tools=[_approve_tool(tools_by_name[name]) for name in JIRA_WRITE_TOOL_NAMES],
    )


def _approve_tool(tool: BaseTool) -> BaseTool:
    """Keep remote execution while adapting its metadata to our bounded contract."""
    tool.description = JIRA_TOOL_DESCRIPTIONS[tool.name]
    tool.args_schema = _openai_compatible_schema(tool.args_schema)
    return tool


def _openai_compatible_schema(schema: object) -> object:
    """Drop optional MCP inputs containing array items OpenAI cannot validate."""
    if isinstance(schema, dict):
        normalized = deepcopy(schema)
    elif isinstance(schema, type) and hasattr(schema, "model_json_schema"):
        normalized = schema.model_json_schema()
    else:
        return schema

    properties = normalized.get("properties")
    removed_properties: set[str] = set()
    if isinstance(properties, dict):
        for name, property_schema in tuple(properties.items()):
            if _contains_untyped_array_items(property_schema):
                properties.pop(name)
                removed_properties.add(name)

    required = normalized.get("required")
    if isinstance(required, list):
        normalized["required"] = [field for field in required if field not in removed_properties]
    return normalized


def _contains_untyped_array_items(schema: object) -> bool:
    """Return whether any array item schema lacks a concrete JSON Schema type."""
    if not isinstance(schema, dict):
        return False

    items = schema.get("items")
    if isinstance(items, dict) and "type" not in items:
        return True

    return any(_contains_untyped_array_items(value) for value in schema.values())
