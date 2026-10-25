"""Application service for the constrained, human-approved Jira ticket flow."""

from typing import Any

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import Settings
from incidentflow.domain.jira.models import (
    JiraIssueCommentRequest,
    JiraIssueCreateRequest,
    JiraMCPResult,
)


class JiraMCPNotEnabledError(RuntimeError):
    """Raised when Jira MCP has not been deliberately enabled by an administrator."""


class JiraTicketService:
    def __init__(self, settings: Settings, client: JiraMCPClient | None = None) -> None:
        self.settings = settings
        self.client = client or JiraMCPClient(settings.jira_mcp_url)

    def _require_read_access(self) -> None:
        if not self.settings.jira_mcp_enabled:
            raise JiraMCPNotEnabledError("Jira MCP is disabled. Set JIRA_MCP_ENABLED=true first.")

    def _require_write_access(self) -> None:
        self._require_read_access()
        if not self.settings.jira_mcp_write_enabled:
            raise JiraMCPNotEnabledError(
                "Jira MCP writes are disabled. Set JIRA_MCP_WRITE_ENABLED=true after review."
            )

    async def get_resources(self) -> JiraMCPResult:
        return await self._invoke_read("getAccessibleAtlassianResources", {})

    async def get_projects(self, cloud_id: str) -> JiraMCPResult:
        return await self._invoke_read("listJiraProjects", {"cloudId": cloud_id})

    async def get_issue_types(self, cloud_id: str, project_key: str) -> JiraMCPResult:
        return await self._invoke_read(
            "listJiraProjectIssueTypesMetadata",
            {"cloudId": cloud_id, "projectKey": project_key},
        )

    async def create_issue(self, request: JiraIssueCreateRequest) -> JiraMCPResult:
        self._require_write_access()
        return await self._invoke_ticket_write("createJiraIssue", request.tool_arguments())

    async def add_comment(self, request: JiraIssueCommentRequest) -> JiraMCPResult:
        self._require_write_access()
        return await self._invoke_ticket_write(
            "addOrEditJiraIssueComment", request.tool_arguments()
        )

    async def _invoke_read(self, operation: str, arguments: dict[str, str]) -> JiraMCPResult:
        self._require_read_access()
        async with self.client.read_tools() as tool_set:
            result = await tool_set.get(operation).ainvoke(arguments)
        return JiraMCPResult(operation=operation, result=_serializable_result(result))

    async def _invoke_ticket_write(
        self, operation: str, arguments: dict[str, str]
    ) -> JiraMCPResult:
        async with self.client.ticket_tools() as tool_set:
            result = await tool_set.get(operation).ainvoke(arguments)
        return JiraMCPResult(operation=operation, result=_serializable_result(result))


def _serializable_result(result: Any) -> Any:
    """Return MCP tool output in a FastAPI-safe form without interpreting its content."""
    if isinstance(result, (str, int, float, bool, list, dict)) or result is None:
        return result
    if hasattr(result, "content"):
        return {"content": result.content}
    return str(result)
