"""Encrypted, durable OAuth state for the Jira MCP client and a browserless OAuth flow."""

import os
import warnings
from pathlib import Path

from cryptography.fernet import Fernet
from fastmcp.client.auth import OAuth
from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.shared.auth import AuthorizationCodeResult

from incidentflow.core.config import Settings

JIRA_AUTHORIZATION_REQUIRED_MESSAGE = (
    "Jira authorization expired or missing; run scripts/authorize_jira.py."
)


class JiraAuthorizationRequiredError(RuntimeError):
    """No usable Jira token exists and this process must not start a browser flow."""

    def __init__(self, message: str = JIRA_AUTHORIZATION_REQUIRED_MESSAGE) -> None:
        super().__init__(message)


class NonInteractiveOAuth(OAuth):
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


def _dynamodb_region(settings: Settings) -> str:
    return os.environ.get("AWS_REGION") or settings.job_queue_region or "us-east-1"


def _dynamodb_store(table: str, region: str) -> AsyncKeyValue:
    """Build the store offline; it connects and checks the table on first use."""
    from key_value.aio.stores.dynamodb import DynamoDBStore

    with warnings.catch_warnings():
        # The library flags DynamoDBStore as an unstable API on every construction.
        warnings.filterwarnings("ignore", message="A configured store is unstable")
        # The table is owned by the infrastructure stack, so never create it here.
        return DynamoDBStore(table_name=table, region_name=region, auto_create=False)
