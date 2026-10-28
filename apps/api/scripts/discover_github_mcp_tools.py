"""Verify that the configured GitHub MCP server exposes IncidentFlow's read-only tools."""

import asyncio

from incidentflow.agent.mcp_clients.github import GitHubMCPClient, select_read_tools
from incidentflow.core.config import get_settings


async def run() -> None:
    settings = get_settings()
    if not settings.github_mcp_is_configured:
        raise RuntimeError("Configure the GitHub MCP transport before discovering tools.")

    if settings.github_mcp_transport == "http":
        client = GitHubMCPClient(server_url=settings.github_mcp_url)
        connection = settings.github_mcp_url
    else:
        client = GitHubMCPClient(
            command=settings.github_mcp_command,
            command_args=settings.github_mcp_stdio_arguments,
            personal_access_token=settings.github_personal_access_token,
        )
        connection = f"stdio command: {settings.github_mcp_command}"
    tools = await client.list_tools()
    try:
        approved = select_read_tools(tools)
    except RuntimeError:
        print("GitHub MCP exposed these tool names:")
        for tool in sorted(tools, key=lambda item: item.name):
            print(f"- {tool.name}")
        raise

    print(f"Connected to GitHub MCP via {connection}")
    print("Approved read-only tools:")
    for tool in approved.read_tools:
        print(f"- {tool.name}")


if __name__ == "__main__":
    asyncio.run(run())
