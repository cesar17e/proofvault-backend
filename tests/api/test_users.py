from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_jwt_verifier
from app.api.router import api_router
from app.auth import (
    InvalidAccessTokenError,
    JWKSUnavailableError,
    SupabaseJWTClaims,
)
from app.core.config import Settings, get_settings


USER_ID = UUID("323e4567-e89b-12d3-a456-426614174000")
OTHER_USER_ID = UUID("523e4567-e89b-12d3-a456-426614174000")
SESSION_ID = UUID("423e4567-e89b-12d3-a456-426614174000")


def make_claims(
    *,
    user_id: UUID = USER_ID,
    email: str = "student@example.com",
) -> SupabaseJWTClaims:
    return SupabaseJWTClaims(
        iss="https://project-ref.supabase.co/auth/v1",
        aud="authenticated",
        exp=2_000_000_000,
        iat=1_900_000_000,
        sub=user_id,
        role="authenticated",
        aal="aal1",
        session_id=SESSION_ID,
        email=email,
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

        assert token == "synthetic-token"
        assert self.claims is not None
        return self.claims


def make_test_client(verifier: StubVerifier) -> TestClient:
    application = FastAPI()
    application.include_router(api_router)
    application.dependency_overrides[get_jwt_verifier] = lambda: verifier
    application.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:password@localhost/proofvault",
        supabase_url="https://project-ref.supabase.co",
    )
    return TestClient(application)


@pytest.mark.parametrize(
    ("user_id", "email"),
    [
        (USER_ID, "student-a@example.com"),
        (OTHER_USER_ID, "student-b@example.com"),
    ],
)
def test_users_me_returns_verified_identity(user_id, email) -> None:
    client = make_test_client(
        StubVerifier(claims=make_claims(user_id=user_id, email=email))
    )

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer synthetic-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "email": email,
    }


def test_users_me_normalizes_empty_email_to_null() -> None:
    client = make_test_client(StubVerifier(claims=make_claims(email="")))

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer synthetic-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(USER_ID),
        "email": None,
    }


def test_users_me_requires_bearer_credentials() -> None:
    client = make_test_client(StubVerifier(claims=make_claims()))

    response = client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_users_me_rejects_invalid_token() -> None:
    client = make_test_client(
        StubVerifier(error=InvalidAccessTokenError("internal detail"))
    )

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer synthetic-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert "internal detail" not in response.text
    assert "synthetic-token" not in response.text


def test_users_me_reports_jwks_outage() -> None:
    client = make_test_client(
        StubVerifier(error=JWKSUnavailableError("internal detail"))
    )

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer synthetic-token"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Authentication service temporarily unavailable"
    }
    assert "internal detail" not in response.text
    assert "synthetic-token" not in response.text


def test_users_me_openapi_contract() -> None:
    client = make_test_client(StubVerifier(claims=make_claims()))

    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/users/me"]["get"]
    response_schema = operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert operation["tags"] == ["users"]
    assert operation["security"] == [{"SupabaseAccessToken": []}]
    assert response_schema == {
        "$ref": "#/components/schemas/UserMeResponse"
    }


def test_health_remains_public_and_unversioned() -> None:
    verifier = StubVerifier(claims=make_claims())
    client = make_test_client(verifier)
    schema = client.get("/openapi.json").json()
    response = client.get("/health")

    assert "/health" in schema["paths"]
    assert "/api/v1/health" not in schema["paths"]
    assert "security" not in schema["paths"]["/health"]["get"]
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "proofvault-api",
    }
    assert verifier.tokens == []
