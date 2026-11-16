"""Cognito access-token verification and viewer/operator route permissions."""

import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWKClientConnectionError

from incidentflow.api.routes.incidents import get_incident_service
from incidentflow.api.routes.incidents import router as incidents_router
from incidentflow.api.routes.investigations import get_investigation_service
from incidentflow.api.routes.investigations import router as investigations_router
from incidentflow.core.auth import get_jwks_client
from incidentflow.core.config import get_settings
from incidentflow.domain.investigations.models import Investigation, InvestigationLifecycle

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool"
CLIENT_ID = "incidentflow-web-client"
KEY_ID = "test-key"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWKClient(PyJWKClient):
    """Serve the locally generated public key instead of fetching the pool's JWKS."""

    def __init__(self, *, reachable: bool = True) -> None:
        super().__init__(f"{ISSUER}/.well-known/jwks.json")
        self.reachable = reachable

    def fetch_data(self) -> Any:
        if not self.reachable:
            raise PyJWKClientConnectionError("JWKS endpoint unreachable")
        jwk = RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": KEY_ID, "use": "sig", "alg": "RS256"}]}


def make_token(**overrides: Any) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "user-sub",
        "token_use": "access",
        "client_id": CLIENT_ID,
        "username": "alice",
        "cognito:groups": ["operator"],
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": KEY_ID})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class FakeInvestigationService:
    def __init__(self) -> None:
        self.investigation_id = uuid4()
        self.resolved_actors: list[str] = []

    def _investigation(self, lifecycle: InvestigationLifecycle) -> Investigation:
        return Investigation(
            id=self.investigation_id,
            incident_id=uuid4(),
            incident_request="Investigate Payment API HTTP 500 errors.",
            incident_business_status="OPEN",
            lifecycle=lifecycle,
            workflow_thread_id=f"investigation:{self.investigation_id}",
        )

    def start_investigation(self, data):
        return self._investigation(InvestigationLifecycle.PENDING)

    def list_investigations(self):
        return [self._investigation(InvestigationLifecycle.COMPLETED)]

    def get_investigation(self, investigation_id: UUID):
        return self._investigation(InvestigationLifecycle.COMPLETED)

    def request_human_review_resume(self, investigation_id: UUID, decision):
        self.resolved_actors.append(decision.actor)
        return self._investigation(InvestigationLifecycle.PENDING)


class FakeIncidentService:
    def list_incidents(self):
        return []


@pytest.fixture
def service() -> FakeInvestigationService:
    return FakeInvestigationService()


@pytest.fixture
def auth_enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER_URL", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def build_client(
    service: FakeInvestigationService, jwks_client: PyJWKClient | None = None
) -> TestClient:
    app = FastAPI()
    app.include_router(incidents_router, prefix="/api")
    app.include_router(investigations_router, prefix="/api")
    app.dependency_overrides[get_investigation_service] = lambda: service
    app.dependency_overrides[get_incident_service] = FakeIncidentService
    app.dependency_overrides[get_jwks_client] = lambda: jwks_client or FakeJWKClient()
    return TestClient(app)


def start(client: TestClient, headers: dict[str, str] | None = None):
    return client.post(
        "/api/investigations",
        json={"incident_id": str(uuid4()), "incident_request": "Investigate HTTP 500s."},
        headers=headers or {},
    )


def assert_authentication_required(response) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_valid_operator_token_starts_investigation(auth_enabled, service) -> None:
    response = start(build_client(service), bearer(make_token()))

    assert response.status_code == 202
    assert response.json()["lifecycle"] == "PENDING"


def test_missing_token_returns_401(auth_enabled, service) -> None:
    client = build_client(service)

    assert_authentication_required(start(client))
    assert_authentication_required(client.get("/api/investigations"))
    assert_authentication_required(
        client.get("/api/incidents", headers={"Authorization": "Basic abc"})
    )


def test_expired_token_returns_401(auth_enabled, service) -> None:
    token = make_token(exp=int(time.time()) - 60)

    assert_authentication_required(start(build_client(service), bearer(token)))


def test_wrong_client_id_returns_401(auth_enabled, service) -> None:
    token = make_token(client_id="another-client")

    assert_authentication_required(start(build_client(service), bearer(token)))


def test_wrong_issuer_returns_401(auth_enabled, service) -> None:
    token = make_token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other")

    assert_authentication_required(start(build_client(service), bearer(token)))


def test_token_signed_by_unknown_key_returns_401(auth_enabled, service) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = jwt.decode(make_token(), options={"verify_signature": False})
    forged = jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": KEY_ID})

    assert_authentication_required(start(build_client(service), bearer(forged)))


def test_id_token_rejected(auth_enabled, service) -> None:
    token = make_token(
        token_use="id",
        client_id=None,
        aud=CLIENT_ID,
        username=None,
        **{"cognito:username": "alice"},
    )

    assert_authentication_required(start(build_client(service), bearer(token)))


def test_access_token_check_rejects_other_token_use(auth_enabled, service) -> None:
    token = make_token(token_use="id")

    assert_authentication_required(start(build_client(service), bearer(token)))


def test_issuer_setting_with_trailing_slash_still_verifies(
    auth_enabled, monkeypatch: pytest.MonkeyPatch, service
) -> None:
    monkeypatch.setenv("OIDC_ISSUER_URL", f"{ISSUER}/")
    get_settings.cache_clear()

    assert start(build_client(service), bearer(make_token())).status_code == 202


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/incidents", {}),
        ("/api/investigations/{id}/human-review/resolve", {"decision": "APPROVE", "actor": "x"}),
        ("/api/investigations/{id}/memory-lessons", {}),
    ],
)
def test_viewer_cannot_operate_returns_403(
    auth_enabled, service, path: str, body: dict[str, str]
) -> None:
    client = build_client(service)
    token = make_token(**{"cognito:groups": ["viewer"]})

    response = client.post(
        path.format(id=service.investigation_id), json=body, headers=bearer(token)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Not allowed."}
    assert service.resolved_actors == []


def test_viewer_cannot_start_returns_403(auth_enabled, service) -> None:
    client = build_client(service)
    token = make_token(**{"cognito:groups": ["viewer"]})

    response = start(client, bearer(token))

    assert response.status_code == 403
    assert response.json() == {"detail": "Not allowed."}
    assert client.get("/api/investigations", headers=bearer(token)).status_code == 200


def test_user_without_group_gets_403_on_reads(auth_enabled, service) -> None:
    client = build_client(service)
    headers = bearer(make_token(**{"cognito:groups": None}))

    for path in (
        "/api/incidents",
        "/api/investigations",
        f"/api/investigations/{service.investigation_id}",
        f"/api/investigations/{service.investigation_id}/trace",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.json() == {"detail": "Not allowed."}


def test_operator_can_read(auth_enabled, service) -> None:
    response = build_client(service).get("/api/incidents", headers=bearer(make_token()))

    assert response.status_code == 200


def test_jwks_unreachable_returns_503(auth_enabled, service) -> None:
    client = build_client(service, FakeJWKClient(reachable=False))

    response = start(client, bearer(make_token()))

    assert response.status_code == 503


def test_resolve_records_token_username_as_actor(auth_enabled, service) -> None:
    client = build_client(service)

    response = client.post(
        f"/api/investigations/{service.investigation_id}/human-review/resolve",
        json={"decision": "APPROVE", "actor": "local-operator"},
        headers=bearer(make_token()),
    )

    assert response.status_code == 202
    assert service.resolved_actors == ["alice"]


def test_resolve_accepts_cognito_username_claim(auth_enabled, service) -> None:
    client = build_client(service)
    token = make_token(username=None, **{"cognito:username": "bob"})

    response = client.post(
        f"/api/investigations/{service.investigation_id}/human-review/resolve",
        json={"decision": "APPROVE", "actor": "local-operator"},
        headers=bearer(token),
    )

    assert response.status_code == 202
    assert service.resolved_actors == ["bob"]


def test_auth_disabled_keeps_local_behaviour(service) -> None:
    client = build_client(service, FakeJWKClient(reachable=False))

    assert start(client).status_code == 202
    assert client.get("/api/investigations").status_code == 200
    response = client.post(
        f"/api/investigations/{service.investigation_id}/human-review/resolve",
        json={"decision": "APPROVE", "actor": "local-operator"},
    )

    assert response.status_code == 202
    assert service.resolved_actors == ["local-operator"]


@pytest.mark.parametrize("missing", ["OIDC_ISSUER_URL", "OIDC_CLIENT_ID"])
def test_auth_enabled_without_oidc_settings_fails_at_startup(
    auth_enabled, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    from incidentflow.main import create_app

    monkeypatch.delenv(missing)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="OIDC_ISSUER_URL and OIDC_CLIENT_ID"):
        create_app()
