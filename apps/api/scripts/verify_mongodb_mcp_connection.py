"""Verify the preconfigured MongoDB MCP connection without an LLM."""

import asyncio

from incidentflow.agent.mcp_clients.mongodb import MongoDBMCPClient
from incidentflow.core.config import get_settings


async def run() -> None:
    settings = get_settings()
    async with MongoDBMCPClient(
        settings.mongodb_mcp_url, settings.mongodb_mcp_connection_string
    ).read_tools() as tool_set:
        schema_tool = tool_set.get("collection-schema")
        result = await schema_tool.ainvoke(
            {
                "database": settings.mongodb_mcp_database,
                "collection": settings.mongodb_mcp_events_collection,
            }
        )
        aggregate_tool = tool_set.get("aggregate")
        events = await aggregate_tool.ainvoke(
            {
                "database": settings.mongodb_mcp_database,
                "collection": settings.mongodb_mcp_events_collection,
                "pipeline": [
                    {"$sort": {"timestamp": 1}},
                    {"$limit": 20},
                ],
            }
        )
    print({"schema": result, "events": events})


if __name__ == "__main__":
    asyncio.run(run())
