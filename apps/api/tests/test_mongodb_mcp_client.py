import pytest
from fastmcp.client import StdioTransport
from fastmcp.client.transports import StreamableHttpTransport
from langchain_core.tools import tool

from incidentflow.agent.mcp_clients.mongodb import (
    MONGODB_READ_TOOL_NAMES,
    MONGODB_TOOL_DESCRIPTIONS,
    MongoDBMCPClient,
    _connection_id_from_result,
    _openai_compatible_schema,
    _remove_connection_id,
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


def test_connection_id_is_extracted_and_hidden_from_the_model_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"connectionId": {"type": "string"}, "database": {"type": "string"}},
        "required": ["connectionId", "database"],
    }

    _remove_connection_id(schema)

    assert (
        _connection_id_from_result(
            [{"text": 'Successfully connected. Your connectionId is "connection-123".'}]
        )
        == "connection-123"
    )
    assert schema == {
        "type": "object",
        "properties": {"database": {"type": "string"}},
        "required": ["database"],
    }
    assert "connectionId" not in schema["properties"]


def test_stdio_transport_when_command_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "missing"))
    client = MongoDBMCPClient(
        None,
        "mongodb://secret-host/",
        command="mongodb-mcp-server",
        command_args=("--readOnly",),
    )

    transport = client._client().transport

    assert isinstance(transport, StdioTransport)
    assert transport.command == "mongodb-mcp-server"
    assert transport.args == ["--readOnly"]
    assert transport.env["HOME"] == "/tmp"
    assert transport.env["MDB_MCP_LOG_PATH"] == "/tmp/mongodb-mcp"
    assert "mongodb://secret-host/" not in transport.args


def test_stdio_environment_keeps_a_writable_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    client = MongoDBMCPClient(None, "mongodb://x/", command="mongodb-mcp-server")

    assert client.environment()["HOME"] == str(tmp_path)


def test_http_transport_by_default() -> None:
    client = MongoDBMCPClient("http://127.0.0.1:3000/mcp", "mongodb://x/")

    assert isinstance(client._client().transport, StreamableHttpTransport)


def test_requires_url_or_command() -> None:
    with pytest.raises(ValueError, match="server URL or a stdio command"):
        MongoDBMCPClient(None, "mongodb://x/")
