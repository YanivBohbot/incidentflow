"""Verify an authenticated, read-only Jira MCP call without involving an LLM."""

import asyncio
import json
from typing import Any

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    if not settings.jira_mcp_enabled:
        raise RuntimeError("Set JIRA_MCP_ENABLED=true before running this verification.")

    async with JiraMCPClient(settings.jira_mcp_url).read_tools() as tool_set:
        resources_result = await tool_set.get("getAccessibleAtlassianResources").ainvoke({})
        cloud_id = _first_cloud_id(resources_result)
        await tool_set.get("listJiraProjects").ainvoke({"cloudId": cloud_id})
        search_result = await tool_set.get("searchJiraIssuesUsingJql").ainvoke(
            {"cloudId": cloud_id, "jql": "ORDER BY updated DESC", "maxResults": 1}
        )
        issue_key = _first_issue_key(search_result)
        if issue_key is not None:
            await tool_set.get("getJiraIssue").ainvoke(
                {"cloudId": cloud_id, "issueIdOrKey": issue_key}
            )

    checked = "resources, projects, JQL search"
    if issue_key is not None:
        checked += ", and issue retrieval"
    print(f"Jira MCP read verification succeeded: {checked}.")


def _first_cloud_id(result: Any) -> str:
    """Extract the first accessible Jira cloud ID without logging Jira response data."""
    text = result[0]["text"]
    payload = json.loads(text)
    return payload["data"]["resources"][0]["cloudId"]


def _first_issue_key(result: Any) -> str | None:
    """Return one issue key from the search result without exposing Jira data in logs."""
    text = result[0]["text"]
    payload = json.loads(text)
    return _find_key(payload)


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
