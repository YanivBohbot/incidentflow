"""Verify the preconfigured MongoDB MCP connection without an LLM."""

import asyncio

from incidentflow.agent.mcp_clients.mongodb import MongoDBMCPClient
from incidentflow.core.config import get_settings


async def run() -> None:
    settings = get_settings()
    async with MongoDBMCPClient(settings.mongodb_mcp_url).read_tools() as tool_set:
        schema_tool = tool_set.get("collection-schema")
        result = await schema_tool.ainvoke(
            {
                "database": settings.mongodb_mcp_database,
                "collection": settings.mongodb_mcp_events_collection,
            }
        )
    print(result)


if __name__ == "__main__":
    asyncio.run(run())
