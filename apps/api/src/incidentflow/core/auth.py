"""Cognito access-token verification and the viewer/operator route permissions.

API Gateway already rejects requests without a valid token; the API verifies the token again so
it is not secure only because of its gateway. With AUTH_ENABLED=false (local default) every
request acts as a local operator.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

from incidentflow.core.config import Settings, get_settings

VIEWER_ROLE = "viewer"
OPERATOR_ROLE = "operator"
LOCAL_PRINCIPAL_USERNAME = "local-operator"


@dataclass(frozen=True)
class Principal:
    """The verified caller: its Cognito username and group memberships."""

    username: str
    groups: frozenset[str]


LOCAL_PRINCIPAL = Principal(LOCAL_PRINCIPAL_USERNAME, frozenset({OPERATOR_ROLE}))


class AuthenticationError(Exception):
    """The bearer token is missing, malformed, or fails verification."""


class SigningKeysUnavailableError(Exception):
    """The issuer's JWKS could not be fetched, so no token can be verified right now."""


def jwks_url(issuer_url: str) -> str:
    return f"{issuer_url.rstrip('/')}/.well-known/jwks.json"


@lru_cache
def _cached_jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True)


def get_jwks_client() -> PyJWKClient | None:
    """Return the JWKS client for the configured issuer, or None when auth is off."""
    settings = get_settings()
    if not settings.auth_enabled or not settings.oidc_issuer_url:
        return None
    return _cached_jwks_client(jwks_url(settings.oidc_issuer_url))


def verify_access_token(
    token: str, settings: Settings, *, jwks_client: PyJWKClient | None = None
) -> Principal:
    """Verify a Cognito access token's signature, issuer, expiry, use and client."""
    client_id = settings.oidc_client_id
    if not settings.oidc_issuer_url or not client_id:
        raise AuthenticationError("OIDC issuer and client id are not configured.")
    issuer = settings.oidc_issuer_url.rstrip("/")
    client = jwks_client or _cached_jwks_client(jwks_url(issuer))
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"require": ["exp", "iss", "token_use", "client_id"]},
        )
    except PyJWKClientConnectionError as error:
        raise SigningKeysUnavailableError(str(error)) from error
    except jwt.PyJWTError as error:
        raise AuthenticationError(str(error)) from error

    if claims["token_use"] != "access":
        raise AuthenticationError("Only access tokens are accepted.")
    if claims["client_id"] != client_id:
        raise AuthenticationError("The token was issued to another client.")
    username = claims.get("username") or claims.get("cognito:username")
    if not isinstance(username, str) or not username:
        raise AuthenticationError("The token carries no username.")
    groups = claims.get("cognito:groups") or []
    if not isinstance(groups, list):
        raise AuthenticationError("The token groups claim is malformed.")
    return Principal(username, frozenset(str(group) for group in groups))


def _authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_principal(
    request: Request,
    jwks_client: Annotated[PyJWKClient | None, Depends(get_jwks_client)],
) -> Principal:
    """Resolve the caller from its bearer token, or the local operator when auth is off."""
    settings = get_settings()
    if not settings.auth_enabled:
        return LOCAL_PRINCIPAL
    token = _bearer_token(request)
    if token is None:
        raise _authentication_required()
    try:
        return verify_access_token(token, settings, jwks_client=jwks_client)
    except AuthenticationError as error:
        raise _authentication_required() from error
    except SigningKeysUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
        ) from error


def _effective_roles(principal: Principal) -> frozenset[str]:
    if OPERATOR_ROLE in principal.groups:
        return principal.groups | {VIEWER_ROLE}
    return principal.groups


def require_role(*roles: str) -> Callable[[Principal], Principal]:
    """Build a dependency that admits a principal holding any of the given roles."""
    allowed = frozenset(roles)

    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not _effective_roles(principal) & allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
        return principal

    return dependency


require_viewer = require_role(VIEWER_ROLE)
require_operator = require_role(OPERATOR_ROLE)

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]
OperatorPrincipal = Annotated[Principal, Depends(require_operator)]
