"""Run the bounded, read-only GitHub specialist workflow directly."""

import asyncio

from incidentflow.agent.tools.specialist_delegation import _run_real_github
from incidentflow.core.config import get_settings

INCIDENT_CONTEXT = (
    "Investigate Payment API HTTP 500 errors. Inspect only relevant recent commits and pull "
    "requests in the configured allowed repository. Return a structured finding."
)

async def main() -> int:
    settings = get_settings()
    if not settings.github_mcp_enabled or not settings.github_mcp_allowed_repositories:
        raise RuntimeError("Enable GitHub MCP and configure GITHUB_MCP_REPOSITORIES first.")

    print(await _run_real_github(INCIDENT_CONTEXT))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
