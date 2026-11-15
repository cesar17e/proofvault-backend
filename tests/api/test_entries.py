from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user, get_db, get_jwt_verifier
from app.api.router import api_router
from app.auth import CurrentUser
from app.services import course_service, entry_service


USER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
OTHER_USER_ID = UUID("223e4567-e89b-12d3-a456-426614174000")
ENTRY_ID = UUID("323e4567-e89b-12d3-a456-426614174000")
COURSE_ID = UUID("423e4567-e89b-12d3-a456-426614174000")
SESSION_ID = UUID("523e4567-e89b-12d3-a456-426614174000")
NOW = datetime(2026, 11, 15, tzinfo=UTC)
STATEMENT = "  Suppose $a_n \\to L$.\n\nThen $(a_n)$ is bounded.  "
PROOF = "Choose $N$ such that $|a_n-L|<1$ whenever $n\\ge N$."


def make_user() -> CurrentUser:
    return CurrentUser(
        id=USER_ID,
        email="student@example.com",
        role="authenticated",
        session_id=SESSION_ID,
        aal="aal1",
    )


def make_entry(
    *,
    course_id: UUID | None = COURSE_ID,
    statement: str = STATEMENT,
    proof: str | None = PROOF,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=ENTRY_ID,
        owner_id=USER_ID,
        course_id=course_id,
        title="Convergent sequences are bounded",
        kind="theorem",
        statement=statement,
        proof=proof,
        topic="Sequences",
        source_reference="Lecture 3",
        index_status="pending",
        created_at=NOW,
        updated_at=NOW,
    )


def make_client(*, authenticated: bool = True) -> TestClient:
    application = FastAPI()
    application.include_router(api_router)
    application.dependency_overrides[get_db] = lambda: object()
    application.dependency_overrides[get_jwt_verifier] = lambda: object()
    if authenticated:
        application.dependency_overrides[get_current_user] = make_user
    return TestClient(application)


def valid_payload() -> dict:
    return {
        "course_id": str(COURSE_ID),
        "title": "Convergent sequences are bounded",
        "kind": "theorem",
        "statement": STATEMENT,
        "proof": PROOF,
        "topic": "Sequences",
        "source_reference": "Lecture 3",
    }


def test_create_entry_preserves_source_and_uses_authenticated_owner(
    monkeypatch,
) -> None:
    captured = {}

    def fake_create(session, *, owner_id, payload):
        captured.update(owner_id=owner_id, payload=payload)
        return make_entry(statement=payload.statement, proof=payload.proof)

    monkeypatch.setattr(entry_service, "create_entry", fake_create)
    client = make_client()

    response = client.post("/api/v1/entries", json=valid_payload())

    assert response.status_code == 201
    assert response.json()["id"] == str(ENTRY_ID)
    assert response.json()["statement"] == STATEMENT
    assert response.json()["proof"] == PROOF
    assert response.json()["index_status"] == "pending"
    assert "owner_id" not in response.json()
    assert captured["owner_id"] == USER_ID
    assert captured["payload"].statement == STATEMENT


def test_create_entry_allows_no_course_and_no_proof(monkeypatch) -> None:
    def fake_create(session, *, owner_id, payload):
        assert payload.course_id is None
        assert payload.proof is None
        return make_entry(course_id=None, proof=None)

    monkeypatch.setattr(entry_service, "create_entry", fake_create)
    client = make_client()

    response = client.post(
        "/api/v1/entries",
        json={
            "title": "An unassigned problem",
            "kind": "problem",
            "statement": "Prove that $x^2\\ge 0$ for every real $x$.",
        },
    )

    assert response.status_code == 201
    assert response.json()["course_id"] is None
    assert response.json()["proof"] is None


def test_create_entry_rejects_client_controlled_fields(monkeypatch) -> None:
    called = False

    def fake_create(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(entry_service, "create_entry", fake_create)
    payload = valid_payload()
    payload.update(owner_id=str(OTHER_USER_ID), index_status="ready")
    client = make_client()

    response = client.post("/api/v1/entries", json=payload)

    assert response.status_code == 422
    assert called is False


def test_create_entry_rejects_invalid_mathematical_content(monkeypatch) -> None:
    called = False

    def fake_create(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(entry_service, "create_entry", fake_create)
    payload = valid_payload()
    payload["statement"] = r"$\input{secret}$"
    client = make_client()

    response = client.post("/api/v1/entries", json=payload)

    assert response.status_code == 422
    assert called is False


def test_foreign_or_missing_course_returns_generic_404(monkeypatch) -> None:
    def fake_create(*args, **kwargs):
        raise course_service.CourseNotFoundError

    monkeypatch.setattr(entry_service, "create_entry", fake_create)
    client = make_client()

    response = client.post("/api/v1/entries", json=valid_payload())

    assert response.status_code == 404
    assert response.json() == {"detail": "Course not found"}


def test_get_entry_returns_full_owner_scoped_detail(monkeypatch) -> None:
    captured = {}

    def fake_get(session, *, owner_id, entry_id):
        captured.update(owner_id=owner_id, entry_id=entry_id)
        return make_entry()

    monkeypatch.setattr(entry_service, "get_entry", fake_get)
    client = make_client()

    response = client.get(f"/api/v1/entries/{ENTRY_ID}")

    assert response.status_code == 200
    assert response.json()["statement"] == STATEMENT
    assert response.json()["proof"] == PROOF
    assert captured == {"owner_id": USER_ID, "entry_id": ENTRY_ID}


def test_missing_and_foreign_entry_return_same_404(monkeypatch) -> None:
    def fake_get(*args, **kwargs):
        raise entry_service.EntryNotFoundError

    monkeypatch.setattr(entry_service, "get_entry", fake_get)
    client = make_client()

    response = client.get(f"/api/v1/entries/{ENTRY_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Entry not found"}


def test_entry_endpoints_require_authentication() -> None:
    client = make_client(authenticated=False)

    response = client.get(f"/api/v1/entries/{ENTRY_ID}")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
