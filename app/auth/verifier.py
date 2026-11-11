"""Cryptographic verification for Supabase access tokens."""

from typing import Any, Literal, cast

import jwt
from jwt import PyJWK, PyJWKClient
from jwt.exceptions import (
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKError,
    PyJWKSetError,
)
from pydantic import ValidationError

from app.auth.claims import SupabaseJWTClaims


REQUIRED_CLAIMS = (
    "iss",
    "aud",
    "exp",
    "iat",
    "sub",
    "role",
    "aal",
    "session_id",
    "email",
    "phone",
    "is_anonymous",
)


class InvalidAccessTokenError(Exception):
    """The supplied access token cannot authenticate a ProofVault user."""


class JWKSUnavailableError(Exception):
    """The configured JWKS cannot currently provide verification keys."""


class SupabaseJWTVerifier:
    """Verify Supabase user access tokens without any FastAPI dependency."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        algorithm: Literal["ES256"] = "ES256",
        leeway_seconds: int = 30,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        if algorithm != "ES256":
            raise ValueError("ProofVault only accepts the ES256 algorithm")

        if not issuer:
            raise ValueError("JWT issuer must not be empty")

        if not audience:
            raise ValueError("JWT audience must not be empty")

        if leeway_seconds < 0:
            raise ValueError("JWT leeway must not be negative")

        self._issuer = issuer
        self._audience = audience
        self._algorithm = algorithm
        self._leeway_seconds = leeway_seconds
        self._jwks_client = jwks_client or PyJWKClient(
            jwks_url,
            cache_jwk_set=True,
            lifespan=600,
            timeout=5,
            cooldown_duration=30,
        )

    def verify(self, token: str) -> SupabaseJWTClaims:
        """Return trusted claims or raise a domain-specific verification error."""
        if not isinstance(token, str) or not token:
            raise InvalidAccessTokenError("Access token is invalid")

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise InvalidAccessTokenError("Access token is invalid") from exc

        if header.get("alg") != self._algorithm:
            raise InvalidAccessTokenError("Access token is invalid")

        key_id = header.get("kid")
        if not isinstance(key_id, str) or not key_id:
            raise InvalidAccessTokenError("Access token is invalid")

        signing_key = self._resolve_signing_key(key_id)
        if signing_key.algorithm_name != self._algorithm:
            raise InvalidAccessTokenError("Access token is invalid")

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway_seconds,
                options={"require": list(REQUIRED_CLAIMS)},
            )
            return SupabaseJWTClaims.model_validate(
                cast(dict[str, Any], payload)
            )
        except (InvalidTokenError, ValidationError) as exc:
            raise InvalidAccessTokenError("Access token is invalid") from exc

    def _resolve_signing_key(self, key_id: str) -> PyJWK:
        try:
            return self._jwks_client.get_signing_key(key_id)
        except PyJWKClientConnectionError as exc:
            raise JWKSUnavailableError(
                "JWT verification keys are temporarily unavailable"
            ) from exc
        except (PyJWKError, PyJWKSetError) as exc:
            raise JWKSUnavailableError(
                "JWT verification keys are temporarily unavailable"
            ) from exc
        except PyJWKClientError as exc:
            raise InvalidAccessTokenError("Access token is invalid") from exc
