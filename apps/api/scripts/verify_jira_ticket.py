"""Verify that a known Jira test ticket is searchable and readable through MCP."""

import argparse
import asyncio
import json
from typing import Any

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue_key", help="Jira issue key created for the test.")
    return parser.parse_args()


async def main(issue_key: str) -> None:
    settings = get_settings()
    if not settings.jira_mcp_enabled:
        raise RuntimeError("Set JIRA_MCP_ENABLED=true before this verification.")

    async with JiraMCPClient(settings.jira_mcp_url).read_tools() as tool_set:
        cloud_id = _first_cloud_id(
            await tool_set.get("getAccessibleAtlassianResources").ainvoke({})
        )
        search_result = await tool_set.get("searchJiraIssuesUsingJql").ainvoke(
            {"cloudId": cloud_id, "jql": f"key = {issue_key}", "maxResults": 1}
        )
        if issue_key not in _all_issue_keys(_tool_payload(search_result)):
            raise RuntimeError(f"JQL search did not return {issue_key}.")
        await tool_set.get("getJiraIssue").ainvoke({"cloudId": cloud_id, "issueIdOrKey": issue_key})

    print(f"Jira ticket verification succeeded: {issue_key} was found and read.")


def _first_cloud_id(result: Any) -> str:
    return _tool_payload(result)["data"]["resources"][0]["cloudId"]


def _tool_payload(result: Any) -> dict[str, Any]:
    return json.loads(result[0]["text"])


def _all_issue_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = {value["key"]} if isinstance(value.get("key"), str) else set()
        for nested_value in value.values():
            keys.update(_all_issue_keys(nested_value))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for nested_value in value:
            keys.update(_all_issue_keys(nested_value))
        return keys
    return set()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.issue_key))
