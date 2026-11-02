"""Least-privilege client for the official Jira Cloud MCP server."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from fastmcp import Client
from fastmcp.client.auth import OAuth
from key_value.aio.stores.disk import DiskStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool, StructuredTool

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
        for tool in (*self.read_tools, *self.write_tools):
            if tool.name == name:
                return tool
        raise KeyError(f"Jira MCP tool is not approved: {name}")


class JiraMCPClient:
    """Discover and restrict Jira Cloud MCP tools to approved operations only."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    def _client(self) -> Client:
        return Client(self.server_url, auth=self._oauth_auth())

    def _oauth_auth(self) -> str | OAuth:
        """Use encrypted persistence only when both local OAuth settings are configured."""
        from incidentflow.core.config import get_settings

        settings = get_settings()
        directory = settings.mcp_oauth_token_store_dir
        encryption_key = settings.mcp_oauth_storage_encryption_key
        if not directory and not encryption_key:
            return "oauth"
        if not directory or not encryption_key:
            raise RuntimeError(
                "Configure both MCP_OAUTH_TOKEN_STORE_DIR and "
                "MCP_OAUTH_STORAGE_ENCRYPTION_KEY to persist Jira OAuth tokens."
            )
        return OAuth(
            mcp_url=self.server_url,
            client_name="IncidentFlow Jira MCP",
            token_storage=FernetEncryptionWrapper(
                key_value=DiskStore(directory=Path(directory).expanduser()),
                fernet=Fernet(encryption_key.encode()),
            ),
        )

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
        # OpenAI strict tool schemas require every remaining property and reject
        # required names whose properties were removed during normalisation.
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
