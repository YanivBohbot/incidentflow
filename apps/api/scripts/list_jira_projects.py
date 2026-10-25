"""List accessible Jira projects to select an explicit test target."""

import asyncio
import json
from typing import Any

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    if not settings.jira_mcp_enabled:
        raise RuntimeError("Set JIRA_MCP_ENABLED=true before listing Jira projects.")

    async with JiraMCPClient(settings.jira_mcp_url).read_tools() as tool_set:
        resources_result = await tool_set.get("getAccessibleAtlassianResources").ainvoke({})
        cloud_id = _first_cloud_id(resources_result)
        projects_result = await tool_set.get("listJiraProjects").ainvoke({"cloudId": cloud_id})

    for project in _find_projects(_tool_payload(projects_result)):
        key = project.get("key")
        name = project.get("name")
        if isinstance(key, str) and isinstance(name, str):
            print(f"{key}: {name}")


def _first_cloud_id(result: Any) -> str:
    resources = _tool_payload(result)["data"]["resources"]
    return resources[0]["cloudId"]


def _tool_payload(result: Any) -> dict[str, Any]:
    return json.loads(result[0]["text"])


def _find_projects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if all(isinstance(value.get(field), str) for field in ("key", "name")):
            return [value]
        found: list[dict[str, Any]] = []
        for nested_value in value.values():
            found.extend(_find_projects(nested_value))
        return found
    if isinstance(value, list):
        found = []
        for nested_value in value:
            found.extend(_find_projects(nested_value))
        return found
    return []


if __name__ == "__main__":
    asyncio.run(main())
