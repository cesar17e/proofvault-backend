from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import PyJWKClient
from jwt.algorithms import ECAlgorithm
from jwt.exceptions import PyJWKClientConnectionError

from app.auth import (
    InvalidAccessTokenError,
    JWKSUnavailableError,
    SupabaseJWTVerifier,
)


ISSUER = "https://project-ref.supabase.co/auth/v1"
AUDIENCE = "authenticated"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
KEY_ID = "test-es256-key"


class MockJWKSClient(PyJWKClient):
    def __init__(
        self,
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(JWKS_URL, cooldown_duration=0)
        self.response = response
        self.error = error
        self.fetch_count = 0

    def fetch_data(self) -> dict[str, Any]:
        self.fetch_count += 1
        if self.error is not None:
            raise self.error

        assert self.response is not None
        return deepcopy(self.response)


@pytest.fixture()
def private_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture()
def jwks(private_key) -> dict[str, Any]:
    public_jwk = ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update(
        {
            "alg": "ES256",
            "kid": KEY_ID,
            "use": "sig",
        }
    )
    return {"keys": [public_jwk]}


@pytest.fixture()
def valid_payload() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "sub": str(uuid4()),
        "role": "authenticated",
        "aal": "aal1",
        "session_id": str(uuid4()),
        "email": "student@example.com",
        "phone": "",
        "is_anonymous": False,
    }


def make_verifier(client: PyJWKClient) -> SupabaseJWTVerifier:
    return SupabaseJWTVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url=JWKS_URL,
        jwks_client=client,
    )


def encode_token(
    payload: dict[str, Any],
    private_key,
    *,
    algorithm: str = "ES256",
    key_id: str | None = KEY_ID,
) -> str:
    headers = {} if key_id is None else {"kid": key_id}
    return jwt.encode(
        payload,
        private_key,
        algorithm=algorithm,
        headers=headers,
    )


def test_verifies_valid_es256_token(private_key, jwks, valid_payload) -> None:
    client = MockJWKSClient(jwks)
    verifier = make_verifier(client)

    claims = verifier.verify(encode_token(valid_payload, private_key))

    assert str(claims.sub) == valid_payload["sub"]
    assert claims.role == "authenticated"
    assert claims.is_anonymous is False


def test_accepts_audience_list(private_key, jwks, valid_payload) -> None:
    valid_payload["aud"] = ["authenticated"]
    verifier = make_verifier(MockJWKSClient(jwks))

    claims = verifier.verify(encode_token(valid_payload, private_key))

    assert claims.aud == ["authenticated"]


def test_reuses_cached_mocked_jwks(private_key, jwks, valid_payload) -> None:
    client = MockJWKSClient(jwks)
    verifier = make_verifier(client)
    token = encode_token(valid_payload, private_key)

    verifier.verify(token)
    verifier.verify(token)

    assert client.fetch_count == 1


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "https://other-project.supabase.co/auth/v1"),
        ("aud", "other-audience"),
        ("role", "service_role"),
        ("is_anonymous", True),
        ("sub", "not-a-uuid"),
    ],
)
def test_rejects_invalid_claims(
    private_key,
    jwks,
    valid_payload,
    claim,
    value,
) -> None:
    valid_payload[claim] = value
    verifier = make_verifier(MockJWKSClient(jwks))

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(encode_token(valid_payload, private_key))


@pytest.mark.parametrize(
    "claim",
    [
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
    ],
)
def test_rejects_missing_required_claim(
    private_key,
    jwks,
    valid_payload,
    claim,
) -> None:
    valid_payload.pop(claim)
    verifier = make_verifier(MockJWKSClient(jwks))

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(encode_token(valid_payload, private_key))


def test_rejects_expired_token(private_key, jwks, valid_payload) -> None:
    valid_payload["exp"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    verifier = make_verifier(MockJWKSClient(jwks))

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(encode_token(valid_payload, private_key))


@pytest.mark.parametrize("claim", ["iat", "nbf"])
def test_rejects_future_token_time(
    private_key,
    jwks,
    valid_payload,
    claim,
) -> None:
    valid_payload[claim] = datetime.now(timezone.utc) + timedelta(minutes=1)
    verifier = make_verifier(MockJWKSClient(jwks))

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(encode_token(valid_payload, private_key))


def test_rejects_wrong_signature(jwks, valid_payload) -> None:
    untrusted_key = ec.generate_private_key(ec.SECP256R1())
    verifier = make_verifier(MockJWKSClient(jwks))

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(encode_token(valid_payload, untrusted_key))


def test_rejects_wrong_algorithm(valid_payload) -> None:
    private_key = ec.generate_private_key(ec.SECP384R1())
    verifier = make_verifier(MockJWKSClient({"keys": []}))
    token = encode_token(
        valid_payload,
        private_key,
        algorithm="ES384",
    )

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_rejects_missing_key_id(private_key, valid_payload) -> None:
    verifier = make_verifier(MockJWKSClient({"keys": []}))
    token = encode_token(valid_payload, private_key, key_id=None)

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


@pytest.mark.parametrize("token", ["", "not-a-jwt"])
def test_rejects_malformed_token(token) -> None:
    verifier = make_verifier(MockJWKSClient({"keys": []}))

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_rejects_unknown_key_id(private_key, jwks, valid_payload) -> None:
    verifier = make_verifier(MockJWKSClient(jwks))
    token = encode_token(valid_payload, private_key, key_id="unknown-key")

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_reports_unavailable_jwks(private_key, valid_payload) -> None:
    error = PyJWKClientConnectionError("mocked JWKS outage")
    verifier = make_verifier(MockJWKSClient(error=error))

    with pytest.raises(JWKSUnavailableError):
        verifier.verify(encode_token(valid_payload, private_key))


def test_reports_malformed_jwks(private_key, valid_payload) -> None:
    verifier = make_verifier(MockJWKSClient({"keys": []}))

    with pytest.raises(JWKSUnavailableError):
        verifier.verify(encode_token(valid_payload, private_key))
