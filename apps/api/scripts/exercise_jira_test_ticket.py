"""Create and verify one explicitly approved, synthetic Jira test ticket."""

import asyncio
import json
from typing import Any

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings

PROJECT_KEY = "SCRUM"
SUMMARY = "[IncidentFlow test] Payment API HTTP 500"
DESCRIPTION = "Ticket de test synthétique créé pour valider IncidentFlow et Jira MCP."
LABELS = ["incidentflow-test", "automated-test"]
COMMENT = "Commentaire de test IncidentFlow ajouté après vérification de recherche et lecture."


async def main() -> None:
    settings = get_settings()
    if not settings.jira_mcp_enabled or not settings.jira_mcp_write_enabled:
        raise RuntimeError(
            "Set JIRA_MCP_ENABLED=true and JIRA_MCP_WRITE_ENABLED=true before this test."
        )

    async with JiraMCPClient(settings.jira_mcp_url).ticket_tools() as tool_set:
        cloud_id = _first_cloud_id(
            await tool_set.get("getAccessibleAtlassianResources").ainvoke({})
        )
        created = await tool_set.get("createJiraIssue").ainvoke(
            {
                "cloudId": cloud_id,
                "projectKey": PROJECT_KEY,
                "issueType": "Task",
                "summary": SUMMARY,
                "description": DESCRIPTION,
                "additional_fields": {"labels": LABELS},
            }
        )
        issue_key = _first_issue_key(created)
        if issue_key is None:
            raise RuntimeError("Jira created the ticket but did not return an issue key.")

        await tool_set.get("searchJiraIssuesUsingJql").ainvoke(
            {
                "cloudId": cloud_id,
                "jql": f'project = {PROJECT_KEY} AND labels = "incidentflow-test"',
                "maxResults": 10,
            }
        )
        await tool_set.get("getJiraIssue").ainvoke({"cloudId": cloud_id, "issueIdOrKey": issue_key})
        await tool_set.get("addOrEditJiraIssueComment").ainvoke(
            {
                "cloudId": cloud_id,
                "issueIdOrKey": issue_key,
                "commentBody": COMMENT,
            }
        )

    print(f"Jira ticket test completed successfully: {issue_key}")
    print("Verified: create, JQL search, read, and comment.")


def _first_cloud_id(result: Any) -> str:
    resources = _tool_payload(result)["data"]["resources"]
    return resources[0]["cloudId"]


def _first_issue_key(result: Any) -> str | None:
    return _find_key(_tool_payload(result))


def _tool_payload(result: Any) -> dict[str, Any]:
    return json.loads(result[0]["text"])


def _find_key(value: Any) -> str | None:
    if isinstance(value, dict):
        key = value.get("key")
        if isinstance(key, str) and key:
            return key
        for nested_value in value.values():
            result = _find_key(nested_value)
            if result is not None:
                return result
    if isinstance(value, list):
        for nested_value in value:
            result = _find_key(nested_value)
            if result is not None:
                return result
    return None


if __name__ == "__main__":
    asyncio.run(main())
