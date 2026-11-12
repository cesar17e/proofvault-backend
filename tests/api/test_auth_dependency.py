from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies import auth as auth_dependencies
from app.api.dependencies.auth import (
    CurrentUserDependency,
    get_jwt_verifier,
)
from app.core.config import Settings
from app.auth import (
    CurrentUser,
    InvalidAccessTokenError,
    JWKSUnavailableError,
    SupabaseJWTClaims,
)


USER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
SESSION_ID = UUID("223e4567-e89b-12d3-a456-426614174000")


def make_claims() -> SupabaseJWTClaims:
    return SupabaseJWTClaims(
        iss="https://project-ref.supabase.co/auth/v1",
        aud="authenticated",
        exp=2_000_000_000,
        iat=1_900_000_000,
        sub=USER_ID,
        role="authenticated",
        aal="aal1",
        session_id=SESSION_ID,
        email="student@example.com",
        phone="",
        is_anonymous=False,
    )


class StubVerifier:
    def __init__(
        self,
        *,
        claims: SupabaseJWTClaims | None = None,
        error: Exception | None = None,
    ) -> None:
        self.claims = claims
        self.error = error
        self.tokens: list[str] = []

    def verify(self, token: str) -> SupabaseJWTClaims:
        self.tokens.append(token)
        if self.error is not None:
            raise self.error

        assert self.claims is not None
        return self.claims


def make_test_client(verifier: StubVerifier) -> TestClient:
    application = FastAPI()
    application.dependency_overrides[get_jwt_verifier] = lambda: verifier

    @application.get("/protected")
    def protected(current_user: CurrentUserDependency):
        return {
            "id": str(current_user.id),
            "email": current_user.email,
            "session_id": str(current_user.session_id),
            "aal": current_user.aal,
        }

    return TestClient(application)


def test_returns_trusted_current_user_for_valid_bearer_token() -> None:
    verifier = StubVerifier(claims=make_claims())
    client = make_test_client(verifier)

    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer synthetic-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(USER_ID),
        "email": "student@example.com",
        "session_id": str(SESSION_ID),
        "aal": "aal1",
    }
    assert verifier.tokens == ["synthetic-token"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic credentials"},
        {"Authorization": "Bearer"},
    ],
)
def test_rejects_missing_or_malformed_bearer_credentials(headers) -> None:
    client = make_test_client(StubVerifier(claims=make_claims()))

    response = client.get("/protected", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_maps_invalid_token_to_unauthorized() -> None:
    client = make_test_client(
        StubVerifier(error=InvalidAccessTokenError("internal detail"))
    )

    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert "internal detail" not in response.text
    assert response.headers["www-authenticate"] == "Bearer"


def test_maps_jwks_outage_to_service_unavailable() -> None:
    client = make_test_client(
        StubVerifier(error=JWKSUnavailableError("internal detail"))
    )

    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer valid-looking-token"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Authentication service temporarily unavailable"
    }
    assert "internal detail" not in response.text


def test_openapi_declares_supabase_bearer_security() -> None:
    client = make_test_client(StubVerifier(claims=make_claims()))

    schema = client.get("/openapi.json").json()

    assert schema["components"]["securitySchemes"]["SupabaseAccessToken"] == {
        "type": "http",
        "description": "Supabase Auth user access token",
        "scheme": "bearer",
    }
    assert schema["paths"]["/protected"]["get"]["security"] == [
        {"SupabaseAccessToken": []}
    ]


def test_current_user_is_frozen() -> None:
    current_user = CurrentUser.from_claims(make_claims())

    with pytest.raises(ValidationError):
        current_user.email = "other@example.com"


def test_process_reuses_cached_verifier(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:password@localhost/proofvault",
        supabase_url="https://project-ref.supabase.co",
    )
    auth_dependencies.get_jwt_verifier.cache_clear()
    monkeypatch.setattr(auth_dependencies, "get_settings", lambda: settings)

    try:
        first = auth_dependencies.get_jwt_verifier()
        second = auth_dependencies.get_jwt_verifier()
    finally:
        auth_dependencies.get_jwt_verifier.cache_clear()

    assert first is second
