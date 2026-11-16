"""Encrypted, durable OAuth state for the Jira MCP client and a browserless OAuth flow."""

import logging
import warnings
from pathlib import Path

import httpx2
from cryptography.fernet import Fernet
from fastmcp.client.auth import OAuth
from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.shared.auth import AuthorizationCodeResult, OAuthMetadata
from pydantic import ValidationError

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
    `_refresh_token` then falls back to `<origin>/token`, which Atlassian answers with 404. We
    fill `context.oauth_metadata` from RFC 8414 discovery first. Re-check on an mcp upgrade.
    """

    async def _refresh_token(self) -> httpx2.Request:
        if self.context.oauth_metadata is None:
            self.context.oauth_metadata = await self._discover_authorization_server_metadata()
        return await super()._refresh_token()

    async def _discover_authorization_server_metadata(self) -> OAuthMetadata | None:
        """Fetch the server's RFC 8414 metadata; None lets the SDK's own fallback proceed."""
        base_url = self.context.get_authorization_base_url(self.context.server_url)
        url = f"{base_url}/.well-known/oauth-authorization-server"
        try:
            async with self.httpx_client_factory(
                timeout=httpx2.Timeout(METADATA_DISCOVERY_TIMEOUT_SECONDS)
            ) as client:
                response = await client.get(url)
            if response.status_code != 200:
                logger.warning("OAuth metadata discovery returned %s", response.status_code)
                return None
            return OAuthMetadata.model_validate_json(response.content)
        except (httpx2.HTTPError, ValidationError) as error:
            logger.warning("OAuth metadata discovery failed: %s", type(error).__name__)
            return None


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
        # The library flags DynamoDBStore as an unstable API on every construction.
        warnings.filterwarnings("ignore", message="A configured store is unstable")
        # The table is owned by the infrastructure stack, so never create it here.
        return DynamoDBStore(table_name=table, region_name=region, auto_create=False)
