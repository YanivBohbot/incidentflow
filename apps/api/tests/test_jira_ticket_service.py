from contextlib import asynccontextmanager

import pytest

from incidentflow.agent.mcp_clients.jira import JiraMCPToolSet
from incidentflow.application.services.jira_ticket_service import (
    JiraMCPNotEnabledError,
    JiraTicketService,
)
from incidentflow.core.config import Settings
from incidentflow.domain.jira.models import JiraIssueCreateRequest


class FakeCreateJiraIssueTool:
    name = "createJiraIssue"

    async def ainvoke(self, arguments: dict[str, str]) -> dict[str, str]:
        return {"key": "OPS-42", **arguments}


class FakeJiraMCPClient:
    def __init__(self) -> None:
        self.ticket_connection_open = False

    @asynccontextmanager
    async def ticket_tools(self):
        self.ticket_connection_open = True
        try:
            yield JiraMCPToolSet(read_tools=[], write_tools=[FakeCreateJiraIssueTool()])
        finally:
            self.ticket_connection_open = False


def _settings(*, enabled: bool, writes_enabled: bool) -> Settings:
    return Settings(
        openai_api_key="test-key",
        database_url="postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
        jira_mcp_enabled=enabled,
        jira_mcp_write_enabled=writes_enabled,
    )


def _run_immediate(coroutine):
    """Drive a no-I/O coroutine without creating a Windows event loop in this unit test."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("The fake Jira MCP call unexpectedly awaited I/O.")


def test_ticket_creation_calls_only_the_approved_mcp_tool() -> None:
    client = FakeJiraMCPClient()
    service = JiraTicketService(_settings(enabled=True, writes_enabled=True), client=client)
    request = JiraIssueCreateRequest(
        cloudId="cloud-123",
        projectKey="OPS",
        issueType="Incident",
        summary="Payment API is returning HTTP 500",
        description="Created from IncidentFlow after human review.",
    )

    result = _run_immediate(service.create_issue(request))

    assert result.operation == "createJiraIssue"
    assert result.result["key"] == "OPS-42"
    assert client.ticket_connection_open is False


def test_ticket_creation_requires_an_explicit_write_enablement() -> None:
    service = JiraTicketService(_settings(enabled=True, writes_enabled=False))
    request = JiraIssueCreateRequest(
        cloudId="cloud-123",
        projectKey="OPS",
        issueType="Incident",
        summary="Payment API is returning HTTP 500",
        description="Created from IncidentFlow after human review.",
    )

    with pytest.raises(JiraMCPNotEnabledError, match="writes are disabled"):
        _run_immediate(service.create_issue(request))
