"""Read-only client for the official MongoDB MCP Server."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass

from fastmcp import Client
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

MONGODB_READ_TOOL_NAMES = (
    "collection-schema",
    "find",
    "aggregate",
)
MONGODB_TOOL_DESCRIPTIONS = {
    "collection-schema": "Read the schema of the configured operational event collection.",
    "find": "Read a bounded set of operational event documents from MongoDB.",
    "aggregate": "Read a bounded, ordered aggregation of operational events from MongoDB.",
}


@dataclass(frozen=True)
class MongoDBMCPToolSet:
    """The deliberately small MongoDB MCP surface available to IncidentFlow."""

    read_tools: list[BaseTool]

    def get(self, name: str) -> BaseTool:
        for mcp_tool in self.read_tools:
            if mcp_tool.name == name:
                return mcp_tool
        raise KeyError(f"MongoDB MCP tool is not approved: {name}")


class MongoDBMCPClient:
    """Discover and restrict MongoDB MCP tools to operational read operations."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    def _client(self) -> Client:
        return Client(self.server_url)

    @asynccontextmanager
    async def read_tools(self) -> AsyncIterator[MongoDBMCPToolSet]:
        """Keep the local MongoDB MCP connection alive while tools are invoked."""
        async with MCPAdapter(self._client()) as adapter:
            yield select_read_tools(await adapter.list_tools())

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
