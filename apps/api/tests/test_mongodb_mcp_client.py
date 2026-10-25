import pytest
from langchain_core.tools import tool

from incidentflow.agent.mcp_clients.mongodb import (
    MONGODB_READ_TOOL_NAMES,
    MONGODB_TOOL_DESCRIPTIONS,
    _openai_compatible_schema,
    select_read_tools,
)


def _tool(name: str):
    @tool(name)
    def fixture_tool() -> str:
        """Test tool."""
        return name

    return fixture_tool


def test_select_read_tools_returns_only_approved_mongodb_operations() -> None:
    tools = [
        _tool(name) for name in (*MONGODB_READ_TOOL_NAMES, "connect", "disconnect", "delete-many")
    ]

    selected = select_read_tools(tools).read_tools

    assert [tool.name for tool in selected] == list(MONGODB_READ_TOOL_NAMES)
    assert {"connect", "disconnect", "delete-many"}.isdisjoint(tool.name for tool in selected)
    assert [tool.description for tool in selected] == [
        MONGODB_TOOL_DESCRIPTIONS[name] for name in MONGODB_READ_TOOL_NAMES
    ]


def test_select_read_tools_rejects_an_incomplete_mongodb_catalog() -> None:
    with pytest.raises(RuntimeError, match="missing required read tools"):
        select_read_tools([_tool("find")])


def test_schema_removes_property_names_from_mongodb_tool_arguments() -> None:
    schema = {
        "type": "object",
        "properties": {
            "sort": {
                "type": "object",
                "propertyNames": {"pattern": "^[a-z_]+$"},
                "additionalProperties": {"type": "integer"},
            }
        },
    }

    normalized = _openai_compatible_schema("find", schema)

    assert normalized == {
        "type": "object",
        "properties": {},
    }
    assert schema["properties"]["sort"]["propertyNames"] == {"pattern": "^[a-z_]+$"}
