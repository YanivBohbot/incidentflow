"""List the tools the configured CloudWatch MCP server exposes and the three IncidentFlow uses."""

import asyncio

from incidentflow.agent.mcp_clients.cloudwatch import CLOUDWATCH_READ_TOOL_NAMES
from incidentflow.agent.tools.cloudwatch_tools import _create_cloudwatch_mcp_client
from incidentflow.core.config import get_settings


async def run() -> None:
    settings = get_settings()
    names = sorted(
        tool.name for tool in await _create_cloudwatch_mcp_client().list_all_server_tools()
    )
    print(
        f"Connected with profile {settings.cloudwatch_mcp_aws_profile or '(default chain)'} "
        f"in {settings.cloudwatch_mcp_aws_region}. The server exposes {len(names)} tools:"
    )
    for name in names:
        marker = "used by IncidentFlow" if name in CLOUDWATCH_READ_TOOL_NAMES else "not used"
        print(f"- {name} ({marker})")
    missing = [name for name in CLOUDWATCH_READ_TOOL_NAMES if name not in names]
    if missing:
        raise SystemExit(f"Missing required tools: {', '.join(missing)}")


if __name__ == "__main__":
    asyncio.run(run())
