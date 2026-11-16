import asyncio
import time
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

import pytest
from cryptography.fernet import Fernet
from key_value.aio.stores.memory import MemoryStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from incidentflow.agent.findings import ITOperationsFinding
from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.agent.mcp_clients.oauth_store import (
    JiraAuthorizationRequiredError,
    NonInteractiveOAuth,
    RefreshingOAuth,
    build_oauth_token_storage,
)
from incidentflow.agent.tools import it_operations_tools
from incidentflow.core.config import get_settings


def _configure_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    store: str = "disk",
    directory: str = "",
    table: str = "",
    key: str = "",
) -> None:
    # Explicit (possibly empty) process values override a developer's local .env.
    monkeypatch.setenv("MCP_OAUTH_TOKEN_STORE", store)
    monkeypatch.setenv("MCP_OAUTH_TOKEN_STORE_DIR", directory)
    monkeypatch.setenv("MCP_OAUTH_DYNAMODB_TABLE", table)
    monkeypatch.setenv("MCP_OAUTH_STORAGE_ENCRYPTION_KEY", key)
    get_settings.cache_clear()


def test_dynamodb_store_selected_when_configured(monkeypatch) -> None:
    from key_value.aio.stores.dynamodb import DynamoDBStore

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    _configure_store(monkeypatch, store="dynamodb", table="t", key=Fernet.generate_key().decode())

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        storage = build_oauth_token_storage(get_settings())

    assert isinstance(storage, FernetEncryptionWrapper)
    assert isinstance(storage.key_value, DynamoDBStore)
    assert storage.key_value._table_name == "t"
    assert storage.key_value._auto_create is False


def test_disk_store_selected_when_configured(monkeypatch, tmp_path) -> None:
    from key_value.aio.stores.disk import DiskStore

    _configure_store(
        monkeypatch, directory=str(tmp_path / "tokens"), key=Fernet.generate_key().decode()
    )

    storage = build_oauth_token_storage(get_settings())

    assert isinstance(storage, FernetEncryptionWrapper)
    assert isinstance(storage.key_value, DiskStore)


def test_no_store_when_nothing_is_configured(monkeypatch) -> None:
    _configure_store(monkeypatch)

    assert build_oauth_token_storage(get_settings()) is None


def test_disk_store_requires_both_settings(monkeypatch, tmp_path) -> None:
    _configure_store(monkeypatch, directory=str(tmp_path / "tokens"))

    with pytest.raises(RuntimeError, match="Configure both"):
        build_oauth_token_storage(get_settings())


def test_dynamodb_store_requires_table_and_key(monkeypatch) -> None:
    _configure_store(monkeypatch, store="dynamodb", key=Fernet.generate_key().decode())

    with pytest.raises(RuntimeError, match="MCP_OAUTH_DYNAMODB_TABLE"):
        build_oauth_token_storage(get_settings())


def test_non_interactive_oauth_fails_fast_without_tokens() -> None:
    auth = NonInteractiveOAuth(
        mcp_url="https://example.invalid/mcp",
        client_name="IncidentFlow test",
        token_storage=FernetEncryptionWrapper(
            key_value=MemoryStore(), fernet=Fernet(Fernet.generate_key())
        ),
    )

    async def exercise() -> None:
        async with asyncio.timeout(5):
            with pytest.raises(JiraAuthorizationRequiredError, match="authorize_jira.py"):
                await auth.redirect_handler("https://example.invalid/authorize")
            with pytest.raises(JiraAuthorizationRequiredError, match="authorize_jira.py"):
                await auth.callback_handler()

    asyncio.run(exercise())


def test_jira_client_is_non_interactive_by_default(monkeypatch, tmp_path) -> None:
    _configure_store(
        monkeypatch, directory=str(tmp_path / "tokens"), key=Fernet.generate_key().decode()
    )
    monkeypatch.setenv("MCP_OAUTH_INTERACTIVE", "false")
    get_settings.cache_clear()
    storage = build_oauth_token_storage(get_settings())

    default_auth = JiraMCPClient("https://example.test/mcp")._oauth_auth(storage)
    interactive_auth = JiraMCPClient("https://example.test/mcp", interactive=True)._oauth_auth(
        storage
    )

    assert isinstance(default_auth, NonInteractiveOAuth)
    assert not isinstance(interactive_auth, NonInteractiveOAuth)
    assert isinstance(interactive_auth, RefreshingOAuth)


class _UnauthorizedJiraClient:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    @asynccontextmanager
    async def read_tools(self) -> AsyncIterator[None]:
        raise self._error
        yield  # pragma: no cover - makes this an async generator


def _wrapped_authorization_error() -> BaseException:
    try:
        try:
            raise JiraAuthorizationRequiredError()
        except JiraAuthorizationRequiredError as error:
            raise RuntimeError("Client failed to connect") from error
    except RuntimeError as wrapped:
        return ExceptionGroup("unhandled errors in a TaskGroup", [wrapped])


@pytest.mark.parametrize(
    "error",
    [JiraAuthorizationRequiredError(), _wrapped_authorization_error()],
    ids=["direct", "wrapped"],
)
def test_jira_finding_reports_reauthorization_within_bound(monkeypatch, error) -> None:
    monkeypatch.setenv("JIRA_MCP_ENABLED", "true")
    monkeypatch.setenv("JIRA_MCP_WRITE_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        it_operations_tools,
        "JiraMCPClient",
        lambda *args, **kwargs: _UnauthorizedJiraClient(error),
    )

    async def delegate() -> str:
        async with asyncio.timeout(5):
            return await it_operations_tools.ask_it_operations.ainvoke(
                {"incident_context": "Payment API HTTP 500"}
            )

    finding = ITOperationsFinding.model_validate_json(asyncio.run(delegate()))

    assert finding.confidence == 0
    assert "authorize_jira.py" in finding.summary


class _ClosableStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeAdapter:
    def __init__(self, client: object) -> None:
        self.client = client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def list_tools(self) -> list:
        return []


@pytest.mark.parametrize("block_raises", [False, True], ids=["completes", "raises"])
def test_jira_client_closes_token_store_after_adapter_block(monkeypatch, block_raises) -> None:
    from incidentflow.agent.mcp_clients import jira

    inner = _ClosableStore()
    storage = FernetEncryptionWrapper(key_value=inner, fernet=Fernet(Fernet.generate_key()))
    monkeypatch.setattr(jira, "build_oauth_token_storage", lambda _settings: storage)
    monkeypatch.setattr(jira, "Client", lambda url, auth: (url, auth))
    monkeypatch.setattr(jira, "MCPAdapter", _FakeAdapter)
    client = JiraMCPClient("https://example.test/mcp", interactive=False)

    async def use_adapter() -> None:
        async with client._adapter():
            assert inner.closed is False
            if block_raises:
                raise RuntimeError("tool call failed")

    if block_raises:
        with pytest.raises(RuntimeError, match="tool call failed"):
            asyncio.run(use_adapter())
    else:
        asyncio.run(use_adapter())
        assert asyncio.run(client.list_tools()) == []

    assert inner.closed is True


_MCP_URL = "https://mcp.example.test/v1/mcp"
_METADATA_URL = "https://mcp.example.test/.well-known/oauth-authorization-server"


async def _seed_expired_tokens(storage: FernetEncryptionWrapper) -> None:
    from fastmcp.client.auth.oauth import TokenStorageAdapter
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

    adapter = TokenStorageAdapter(async_key_value=storage, server_url=_MCP_URL)
    await adapter.set_client_info(
        OAuthClientInformationFull(
            client_id="client-1",
            redirect_uris=["http://localhost:8765/callback"],
            token_endpoint_auth_method="none",
        )
    )
    await adapter.set_tokens(
        OAuthToken(access_token="old", token_type="Bearer", expires_in=3600, refresh_token="r1")
    )
    await storage.put(
        key=adapter._get_token_expiry_cache_key(),
        value={"expires_at": time.time() - 60},
        collection="mcp-oauth-token-expiry",
    )


async def _request_mcp_with_stored_tokens(handler) -> tuple[list[str], int]:
    import httpx2

    seen: list[str] = []

    def recording_handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(f"{request.method} {request.url.copy_with(query=None)}")
        return handler(request)

    transport = httpx2.MockTransport(recording_handler)
    storage = FernetEncryptionWrapper(key_value=MemoryStore(), fernet=Fernet(Fernet.generate_key()))
    await _seed_expired_tokens(storage)
    auth = NonInteractiveOAuth(
        mcp_url=_MCP_URL,
        token_storage=storage,
        httpx_client_factory=lambda **kwargs: httpx2.AsyncClient(transport=transport, **kwargs),
    )
    async with asyncio.timeout(5):
        async with httpx2.AsyncClient(auth=auth, transport=transport) as client:
            response = await client.get(_MCP_URL)
    return seen, response.status_code


def test_stored_token_refresh_uses_the_discovered_token_endpoint() -> None:
    import httpx2

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url.copy_with(query=None))
        if url == _METADATA_URL:
            return httpx2.Response(
                200,
                json={
                    "issuer": "https://mcp.example.test",
                    "authorization_endpoint": "https://mcp.example.test/v1/authorize",
                    "token_endpoint": "https://mcp.example.test/v1/token",
                },
            )
        if url == "https://mcp.example.test/v1/token":
            return httpx2.Response(
                200,
                json={
                    "access_token": "new",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": "r2",
                },
            )
        if url == _MCP_URL and request.headers.get("Authorization") == "Bearer new":
            return httpx2.Response(200, json={})
        return httpx2.Response(404)

    seen, status = asyncio.run(_request_mcp_with_stored_tokens(handler))

    assert status == 200
    assert seen == [
        f"GET {_METADATA_URL}",
        "POST https://mcp.example.test/v1/token",
        f"GET {_MCP_URL}",
    ]


def test_failed_metadata_discovery_still_fails_fast() -> None:
    import httpx2

    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url.copy_with(query=None)) == _MCP_URL:
            return httpx2.Response(401)
        return httpx2.Response(404)

    with pytest.raises(JiraAuthorizationRequiredError):
        asyncio.run(_request_mcp_with_stored_tokens(handler))
