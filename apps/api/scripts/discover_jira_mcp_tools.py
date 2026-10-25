"""Discover the real Jira Cloud MCP tool catalog without invoking Jira tools."""

import asyncio

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    client = JiraMCPClient(settings.jira_mcp_url)
    tools = await client.list_tools()

    print(f"Connected to {settings.jira_mcp_url}")
    print("Discovered tools (none invoked):")
    for tool in tools:
        print(f"- {tool.name}: {tool.description or 'No description supplied.'}")


if __name__ == "__main__":
    asyncio.run(main())
