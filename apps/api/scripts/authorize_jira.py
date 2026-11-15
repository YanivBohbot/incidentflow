"""Authorize Jira MCP in a browser once and save the OAuth state in the configured store."""

import asyncio

from verify_jira_read_access import run_read_checks

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import Settings, get_settings


async def main() -> None:
    settings = get_settings()
    if not settings.jira_mcp_enabled:
        raise RuntimeError("Set JIRA_MCP_ENABLED=true before authorizing Jira.")
    store = describe_token_store(settings)
    if store is None:
        raise RuntimeError(
            "Configure MCP_OAUTH_TOKEN_STORE with its location and "
            "MCP_OAUTH_STORAGE_ENCRYPTION_KEY so the authorization outlives this process."
        )

    checked = await run_read_checks(JiraMCPClient(settings.jira_mcp_url, interactive=True))
    print(f"Jira MCP read verification succeeded: {checked}.")
    print(f"Jira OAuth state saved to {store}.")


def describe_token_store(settings: Settings) -> str | None:
    """Name the store the OAuth state goes to, without revealing any secret."""
    if settings.mcp_oauth_token_store == "dynamodb":
        if settings.mcp_oauth_dynamodb_table:
            return f"DynamoDB table {settings.mcp_oauth_dynamodb_table}"
        return None
    if settings.mcp_oauth_token_store_dir:
        return f"disk directory {settings.mcp_oauth_token_store_dir}"
    return None


if __name__ == "__main__":
    asyncio.run(main())
