"""Encrypted, durable OAuth state for the Jira MCP client and a browserless OAuth flow."""

import logging
import warnings
from pathlib import Path

import anyio
import httpx2
from cryptography.fernet import Fernet
from fastmcp.client.auth import OAuth
from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.client.auth import OAuthFlowError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    issuers_match,
    validate_metadata_issuer,
)
from mcp.shared.auth import AuthorizationCodeResult

from incidentflow.core.config import Settings

logger = logging.getLogger(__name__)

METADATA_DISCOVERY_TIMEOUT_SECONDS = 10.0

JIRA_AUTHORIZATION_REQUIRED_MESSAGE = (
    "Jira authorization expired or missing; run scripts/authorize_jira.py."
)


class JiraAuthorizationRequiredError(RuntimeError):
    """No usable Jira token exists and this process must not start a browser flow."""

    def __init__(self, message: str = JIRA_AUTHORIZATION_REQUIRED_MESSAGE) -> None:
        super().__init__(message)


class RefreshingOAuth(OAuth):
    """OAuth that finds the real token endpoint before refreshing tokens loaded from storage.

    Relies on mcp 2.3.0 internals (`mcp/client/auth/oauth2.py`): `_auth_flow` calls
    `_refresh_token` for an expired stored token before any 401 has run metadata discovery, and
    `_refresh_token` then falls back to `<MCP origin>/token`, which is the wrong server for
    Atlassian (its tokens come from auth.atlassian.com). We first run the same discovery as the
    SDK's 401 branch, using its helpers, and cache the result on the context. Re-check on an mcp
    upgrade.
    """

    async def _refresh_token(self) -> httpx2.Request:
        if self.context.oauth_metadata is None:
            with anyio.move_on_after(METADATA_DISCOVERY_TIMEOUT_SECONDS):
                try:
                    await self._discover_authorization_server_metadata()
                except (httpx2.HTTPError, OAuthFlowError) as error:
                    logger.warning("OAuth metadata discovery failed: %s", type(error).__name__)
        return await super()._refresh_token()

    async def _discover_authorization_server_metadata(self) -> None:
        """Mirror the SDK's 401 discovery: protected resource, then authorization server."""
        server_url = self.context.server_url
        async with self.httpx_client_factory(
            timeout=httpx2.Timeout(METADATA_DISCOVERY_TIMEOUT_SECONDS)
        ) as client:
            for url in build_protected_resource_metadata_discovery_urls(None, server_url):
                prm = await handle_protected_resource_response(
                    await client.send(create_oauth_metadata_request(url))
                )
                if prm is not None:
                    await self._validate_resource_match(prm)
                    self.context.protected_resource_metadata = prm
                    self.context.auth_server_url = self._select_authorization_server(
                        [str(server) for server in prm.authorization_servers]
                    )
                    break

            expected_issuer = self._expected_issuer()
            for url in build_oauth_authorization_server_metadata_discovery_urls(
                self.context.auth_server_url, server_url
            ):
                ok, metadata = await handle_auth_metadata_response(
                    await client.send(create_oauth_metadata_request(url))
                )
                if not ok:
                    return
                if metadata is None:
                    continue
                if self.context.auth_server_url is None and issuers_match(
                    str(metadata.issuer), expected_issuer
                ):
                    expected_issuer = str(metadata.issuer)
                validate_metadata_issuer(metadata, expected_issuer)
                self.context.oauth_metadata = metadata
                return


class NonInteractiveOAuth(RefreshingOAuth):
    """OAuth that refreshes stored tokens but fails fast instead of asking for a browser."""

    async def redirect_handler(self, authorization_url: str) -> None:
        raise JiraAuthorizationRequiredError()

    async def callback_handler(self) -> AuthorizationCodeResult:
        raise JiraAuthorizationRequiredError()


def build_oauth_token_storage(settings: Settings) -> AsyncKeyValue | None:
    """Return the configured encrypted token store, or None when no store is configured."""
    encryption_key = settings.mcp_oauth_storage_encryption_key
    if settings.mcp_oauth_token_store == "dynamodb":
        table = settings.mcp_oauth_dynamodb_table
        if not table or not encryption_key:
            raise RuntimeError(
                "Configure both MCP_OAUTH_DYNAMODB_TABLE and "
                "MCP_OAUTH_STORAGE_ENCRYPTION_KEY to store Jira OAuth tokens in DynamoDB."
            )
        store = _dynamodb_store(table, _dynamodb_region(settings))
    else:
        directory = settings.mcp_oauth_token_store_dir
        if not directory and not encryption_key:
            return None
        if not directory or not encryption_key:
            raise RuntimeError(
                "Configure both MCP_OAUTH_TOKEN_STORE_DIR and "
                "MCP_OAUTH_STORAGE_ENCRYPTION_KEY to persist Jira OAuth tokens."
            )
        from key_value.aio.stores.disk import DiskStore

        store = DiskStore(directory=Path(directory).expanduser())

    return FernetEncryptionWrapper(key_value=store, fernet=Fernet(encryption_key.encode()))


async def close_oauth_token_storage(storage: AsyncKeyValue | None) -> None:
    """Close the store under the encryption wrapper, releasing e.g. its DynamoDB client."""
    inner = getattr(storage, "key_value", storage)
    close = getattr(inner, "close", None)
    if close is not None:
        await close()


def _dynamodb_region(settings: Settings) -> str:
    return settings.queue_region


def _dynamodb_store(table: str, region: str) -> AsyncKeyValue:
    """Build the store offline; it connects and checks the table on first use."""
    from key_value.aio.stores.dynamodb import DynamoDBStore

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="A configured store is unstable")
        return DynamoDBStore(table_name=table, region_name=region, auto_create=False)
