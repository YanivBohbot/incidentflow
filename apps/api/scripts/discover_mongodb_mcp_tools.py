"""Verify that the local MongoDB MCP server exposes IncidentFlow's read-only tools."""

import asyncio

from incidentflow.agent.mcp_clients.mongodb import MongoDBMCPClient, select_read_tools
from incidentflow.core.config import get_settings


async def run() -> None:
    settings = get_settings()
    client = MongoDBMCPClient(settings.mongodb_mcp_url)
    tools = await client.list_tools()
    approved = select_read_tools(tools)

    print(f"Connected to MongoDB MCP at {settings.mongodb_mcp_url}")
    print("Approved read-only tools:")
    for tool in approved.read_tools:
        print(f"- {tool.name}")


if __name__ == "__main__":
    asyncio.run(run())
