"""Expire the stored Jira access token and prove a browserless refresh works."""

import asyncio
import time

from authorize_jira import describe_token_store
from fastmcp.client.auth.oauth import TokenStorageAdapter
from verify_jira_read_access import run_read_checks

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.agent.mcp_clients.oauth_store import build_oauth_token_storage
from incidentflow.core.config import get_settings

# The collection fastmcp's TokenStorageAdapter keeps the absolute token expiry in.
TOKEN_EXPIRY_COLLECTION = "mcp-oauth-token-expiry"


async def main() -> None:
    settings = get_settings()
    if not settings.jira_mcp_enabled:
        raise RuntimeError("Set JIRA_MCP_ENABLED=true before checking the Jira refresh.")
    storage = build_oauth_token_storage(settings)
    if storage is None:
        raise RuntimeError("Configure a Jira OAuth token store before checking the refresh.")
    print(f"Using {describe_token_store(settings)}.")

    # OAuth strips a trailing slash before keying its storage, so do the same here.
    adapter = TokenStorageAdapter(
        async_key_value=storage, server_url=settings.jira_mcp_url.rstrip("/")
    )
    tokens = await adapter.get_tokens()
    if tokens is None:
        print("No stored Jira tokens; run scripts/authorize_jira.py first.")
        return
    if not tokens.refresh_token:
        print("The stored Jira token has no refresh token; a refresh cannot succeed.")
        return
    if not tokens.expires_in:
        # fastmcp only reads the stored expiry when the token carries expires_in.
        print("The stored Jira token has no expires_in; the forced expiry would be ignored.")
        return

    await storage.put(
        key=adapter._get_token_expiry_cache_key(),
        value={"expires_at": time.time() - 60},
        collection=TOKEN_EXPIRY_COLLECTION,
    )

    try:
        await run_read_checks(JiraMCPClient(settings.jira_mcp_url, interactive=False))
    except Exception as error:  # noqa: BLE001 - the class name is the result to report
        print(f"Refresh failed: {type(error).__name__}")
        return
    print("Refresh succeeded")


if __name__ == "__main__":
    asyncio.run(main())
