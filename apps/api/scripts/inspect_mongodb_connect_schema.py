"""Print the model-facing input schema advertised by MongoDB MCP's connect tool."""

import asyncio
import json

from incidentflow.agent.mcp_clients.mongodb import MongoDBMCPClient
from incidentflow.core.config import get_settings


async def run() -> None:
    settings = get_settings()
    tools = await MongoDBMCPClient(settings.mongodb_mcp_url).list_tools()
    connect = next(tool for tool in tools if tool.name == "connect")
    schema = connect.args_schema
    if isinstance(schema, dict):
        print(json.dumps(schema, indent=2, default=str))
    else:
        print(json.dumps(schema.model_json_schema(), indent=2))


if __name__ == "__main__":
    asyncio.run(run())
