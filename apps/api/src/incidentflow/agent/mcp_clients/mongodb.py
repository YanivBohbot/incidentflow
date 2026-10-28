"""Read-only client for the official MongoDB MCP Server."""

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool, StructuredTool

MONGODB_READ_TOOL_NAMES = (
    "collection-schema",
    "find",
    "aggregate",
)
MONGODB_CONNECT_TOOL_NAME = "connect"
MONGODB_TOOL_DESCRIPTIONS = {
    "collection-schema": "Read the schema of the configured operational event collection.",
    "find": "Read a bounded set of operational event documents from MongoDB.",
    "aggregate": "Read a bounded, ordered aggregation of operational events from MongoDB.",
}


@dataclass(frozen=True)
class MongoDBMCPToolSet:
    """The deliberately small MongoDB MCP surface available to IncidentFlow."""

    read_tools: list[BaseTool]
    connection_id: str | None = None

    def get(self, name: str) -> BaseTool:
        for mcp_tool in self.read_tools:
            if mcp_tool.name == name:
                return mcp_tool
        raise KeyError(f"MongoDB MCP tool is not approved: {name}")


class MongoDBMCPClient:
    """Discover and restrict MongoDB MCP tools to operational read operations."""

    def __init__(self, server_url: str, connection_string: str) -> None:
        """Store the MCP endpoint and the connection string used only by the client."""
        self.server_url = server_url
        self.connection_string = connection_string

    def _client(self) -> Client:
        return Client(self.server_url)

    @asynccontextmanager
    async def read_tools(self) -> AsyncIterator[MongoDBMCPToolSet]:
        """Connect once and expose read tools with their connection ID bound internally."""
        async with MCPAdapter(self._client()) as adapter:
            tools = await adapter.list_tools()
            connection_id = await _connect(tools, self.connection_string)
            selected = select_read_tools(tools)
            yield MongoDBMCPToolSet(
                read_tools=_bind_connection_id(selected.read_tools, connection_id),
                connection_id=connection_id,
            )

    async def list_tools(self) -> list[BaseTool]:
        """Discover tool metadata without returning tools intended for later use."""
        async with MCPAdapter(self._client()) as adapter:
            return await adapter.list_tools()


def select_read_tools(tools: Sequence[BaseTool]) -> MongoDBMCPToolSet:
    """Select only approved operational read operations from the MCP catalog."""
    tools_by_name = {tool.name: tool for tool in tools}
    missing_tools = [name for name in MONGODB_READ_TOOL_NAMES if name not in tools_by_name]
    if missing_tools:
        missing_names = ", ".join(missing_tools)
        raise RuntimeError(f"MongoDB MCP server is missing required read tools: {missing_names}")

    approved_tools = []
    for name in MONGODB_READ_TOOL_NAMES:
        tool = tools_by_name[name]
        tool.description = MONGODB_TOOL_DESCRIPTIONS[name]
        tool.args_schema = _openai_compatible_schema(tool.name, tool.args_schema)
        approved_tools.append(tool)

    return MongoDBMCPToolSet(read_tools=approved_tools)


async def _connect(tools: Sequence[BaseTool], connection_string: str) -> str:
    """Open the configured MongoDB deployment and return the server-issued connection ID."""
    tools_by_name = {tool.name: tool for tool in tools}
    connect_tool = tools_by_name.get(MONGODB_CONNECT_TOOL_NAME)
    if connect_tool is None:
        raise RuntimeError("MongoDB MCP server is missing the required connect tool.")
    result = await connect_tool.ainvoke({"connectionString": connection_string})
    connection_id = _connection_id_from_result(result)
    if connection_id is None:
        raise RuntimeError("MongoDB MCP did not return a connectionId.")
    return connection_id


def _connection_id_from_result(result: Any) -> str | None:
    """Extract the opaque connection ID from the official MongoDB MCP response text."""
    values = result if isinstance(result, list) else [result]
    for value in values:
        text = value.get("text", "") if isinstance(value, dict) else str(value)
        match = re.search(r'connectionId is "([^"]+)"', text)
        if match:
            return match.group(1)
    return None


def _bind_connection_id(tools: Sequence[BaseTool], connection_id: str) -> list[BaseTool]:
    """Hide the connection ID from the model and add it to every approved call."""
    return [_bind_tool_connection(tool, connection_id) for tool in tools]


def _bind_tool_connection(tool: BaseTool, connection_id: str) -> BaseTool:
    """Create an equivalent async tool that always targets the connected deployment."""
    schema = _openai_compatible_schema(tool.name, tool.args_schema)
    _remove_connection_id(schema)

    async def invoke_bound_tool(**arguments: Any) -> Any:
        """Forward model arguments with the server-issued connection ID appended."""
        return await tool.ainvoke({**arguments, "connectionId": connection_id})

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=schema,
        coroutine=invoke_bound_tool,
    )


def _openai_compatible_schema(tool_name: str, schema: object) -> object:
    """Remove JSON Schema constraints unsupported by OpenAI function calling."""
    if isinstance(schema, dict):
        normalized = deepcopy(schema)
    elif isinstance(schema, type) and hasattr(schema, "model_json_schema"):
        normalized = schema.model_json_schema()
    else:
        return schema

    if tool_name == "find":
        _remove_incompatible_find_sort(normalized)
    _remove_property_names(normalized)
    return normalized


def _remove_property_names(value: object) -> None:
    """Strip propertyNames recursively without changing the remote MCP tool contract."""
    if isinstance(value, dict):
        value.pop("propertyNames", None)
        for nested_value in value.values():
            _remove_property_names(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _remove_property_names(nested_value)


def _remove_incompatible_find_sort(schema: dict[str, object]) -> None:
    """Remove the find sort input whose dynamic key schema OpenAI cannot represent."""
    properties = schema.get("properties")
    if not isinstance(properties, dict) or "sort" not in properties:
        return

    properties.pop("sort")
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [field for field in required if field != "sort"]


def _remove_connection_id(schema: object) -> None:
    """Remove the internal MCP connection ID from the model-facing JSON schema."""
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if isinstance(properties, dict):
        properties.pop("connectionId", None)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [field for field in required if field != "connectionId"]
