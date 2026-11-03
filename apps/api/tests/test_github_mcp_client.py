import pytest
from langchain_core.tools import tool

from incidentflow.agent.mcp_clients.github import (
    GITHUB_READ_TOOL_NAMES,
    GITHUB_TOOL_DESCRIPTIONS,
    select_read_tools,
)


def _tool(name: str):
    @tool(name)
    def fixture_tool() -> str:
        """Test tool."""
        return name

    return fixture_tool


def test_select_read_tools_excludes_all_github_mutations() -> None:
    tools = [
        _tool(name)
        for name in (*GITHUB_READ_TOOL_NAMES, "create_issue", "merge_pull_request")
    ]

    selected = select_read_tools(tools).read_tools

    assert [tool.name for tool in selected] == list(GITHUB_READ_TOOL_NAMES)
    assert "create_issue" not in [tool.name for tool in selected]
    assert "merge_pull_request" not in [tool.name for tool in selected]
    assert [tool.description for tool in selected] == [
        GITHUB_TOOL_DESCRIPTIONS[name] for name in GITHUB_READ_TOOL_NAMES
    ]


def test_select_read_tools_rejects_an_incomplete_catalog() -> None:
    with pytest.raises(RuntimeError, match="missing required read tools"):
        select_read_tools([_tool("list_commits")])


def test_http_transport_sends_the_pat_and_forces_read_only_mode() -> None:
    from incidentflow.agent.mcp_clients.github import GitHubMCPClient

    client = GitHubMCPClient(
        server_url="https://api.githubcopilot.com/mcp/", personal_access_token="ghp_test"
    )

    headers = client._client().transport.headers

    assert headers["Authorization"] == "Bearer ghp_test"
    assert headers["X-MCP-Readonly"] == "true"
