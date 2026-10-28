import pytest
from fastmcp.client.auth import OAuth
from langchain_core.tools import tool

from incidentflow.agent.mcp_clients.jira import (
    JIRA_READ_TOOL_NAMES,
    JIRA_TOOL_DESCRIPTIONS,
    JIRA_WRITE_TOOL_NAMES,
    JiraMCPClient,
    _openai_compatible_schema,
    select_read_tools,
    select_ticket_tools,
)
from incidentflow.core.config import get_settings


def _tool(name: str):
    @tool(name)
    def fixture_tool() -> str:
        """Test tool."""
        return name

    return fixture_tool


def test_select_read_tools_returns_only_the_approved_names() -> None:
    tools = [_tool(name) for name in (*JIRA_READ_TOOL_NAMES, "executeWrite")]

    selected = select_read_tools(tools).read_tools

    assert [tool.name for tool in selected] == list(JIRA_READ_TOOL_NAMES)
    assert "executeWrite" not in [tool.name for tool in selected]
    assert [tool.description for tool in selected] == [
        JIRA_TOOL_DESCRIPTIONS[name] for name in JIRA_READ_TOOL_NAMES
    ]


def test_select_read_tools_rejects_an_incomplete_catalog() -> None:
    tools = [_tool("unrelated_read_tool")]

    with pytest.raises(RuntimeError, match="missing required read tools"):
        select_read_tools(tools)


def test_select_ticket_tools_excludes_unapproved_mutations() -> None:
    tools = [
        _tool(name) for name in (*JIRA_READ_TOOL_NAMES, *JIRA_WRITE_TOOL_NAMES, "editJiraIssue")
    ]

    selected = select_ticket_tools(tools)

    assert [tool.name for tool in selected.write_tools] == list(JIRA_WRITE_TOOL_NAMES)
    assert "editJiraIssue" not in [tool.name for tool in selected.write_tools]


def test_schema_removes_mcp_only_arguments_with_untyped_array_items() -> None:
    schema = {
        "type": "object",
        "properties": {
            "cloudId": {"type": "string"},
            "jql": {"type": "string"},
            "fields": {"type": "array", "items": {}},
            "properties": {"type": "array", "items": {"anyOf": [{"type": "string"}]}},
            "expand": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["cloudId", "jql", "fields", "properties", "expand"],
    }

    normalized = _openai_compatible_schema(schema)

    assert normalized == {
        "type": "object",
        "properties": {
            "cloudId": {"type": "string"},
            "jql": {"type": "string"},
            "expand": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["cloudId", "jql", "expand"],
    }
    assert schema["properties"]["fields"] == {"type": "array", "items": {}}


def test_jira_client_uses_encrypted_persistent_oauth_when_configured(monkeypatch, tmp_path) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("MCP_OAUTH_TOKEN_STORE_DIR", str(tmp_path / "oauth-tokens"))
    monkeypatch.setenv("MCP_OAUTH_STORAGE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()

    try:
        auth = JiraMCPClient("https://example.test/mcp")._oauth_auth()
    finally:
        get_settings.cache_clear()

    assert isinstance(auth, OAuth)


def test_jira_client_rejects_partially_configured_oauth_persistence(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MCP_OAUTH_TOKEN_STORE_DIR", str(tmp_path / "oauth-tokens"))
    monkeypatch.delenv("MCP_OAUTH_STORAGE_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="Configure both"):
            JiraMCPClient("https://example.test/mcp")._oauth_auth()
    finally:
        get_settings.cache_clear()
