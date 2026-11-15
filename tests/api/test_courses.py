from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user, get_db, get_jwt_verifier
from app.api.router import api_router
from app.auth import CurrentUser
from app.services import course_service


USER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
OTHER_USER_ID = UUID("223e4567-e89b-12d3-a456-426614174000")
COURSE_ID = UUID("323e4567-e89b-12d3-a456-426614174000")
SESSION_ID = UUID("423e4567-e89b-12d3-a456-426614174000")
NOW = datetime(2026, 11, 14, tzinfo=UTC)


def make_user(user_id: UUID = USER_ID) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        email="student@example.com",
        role="authenticated",
        session_id=SESSION_ID,
        aal="aal1",
    )


def make_course(
    *,
    name: str = "Real Analysis",
    description: str | None = "Sequences and limits",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=COURSE_ID,
        owner_id=USER_ID,
        name=name,
        description=description,
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


def test_create_course_uses_authenticated_user(monkeypatch) -> None:
    captured = {}

    def fake_create(session, *, owner_id, payload):
        captured.update(session=session, owner_id=owner_id, payload=payload)
        return make_course(name=payload.name, description=payload.description)

    monkeypatch.setattr(course_service, "create_course", fake_create)
    client = make_client()

    response = client.post(
        "/api/v1/courses",
        json={"name": "Real Analysis", "description": "Sequences and limits"},
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(COURSE_ID)
    assert response.json()["name"] == "Real Analysis"
    assert captured["owner_id"] == USER_ID


def test_course_requests_reject_client_controlled_owner(monkeypatch) -> None:
    called = False

    def fake_create(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(course_service, "create_course", fake_create)
    client = make_client()

    response = client.post(
        "/api/v1/courses",
        json={"name": "Topology", "owner_id": str(OTHER_USER_ID)},
    )

    assert response.status_code == 422
    assert called is False


def test_list_courses_uses_authenticated_owner(monkeypatch) -> None:
    captured = {}

    def fake_list(session, *, owner_id):
        captured["owner_id"] = owner_id
        return [make_course()]

    monkeypatch.setattr(course_service, "list_courses", fake_list)
    client = make_client()

    response = client.get("/api/v1/courses")

    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Real Analysis"
    assert captured["owner_id"] == USER_ID


def test_get_course_returns_owner_scoped_resource(monkeypatch) -> None:
    captured = {}

    def fake_get(session, *, owner_id, course_id):
        captured.update(owner_id=owner_id, course_id=course_id)
        return make_course()

    monkeypatch.setattr(course_service, "get_course", fake_get)
    client = make_client()

    response = client.get(f"/api/v1/courses/{COURSE_ID}")

    assert response.status_code == 200
    assert captured == {"owner_id": USER_ID, "course_id": COURSE_ID}


@pytest.mark.parametrize(
    ("method", "service_name", "request_kwargs"),
    [
        ("GET", "get_course", {}),
        ("PATCH", "update_course", {"json": {"name": "Topology"}}),
        ("DELETE", "delete_course", {}),
    ],
)
def test_missing_and_foreign_courses_return_same_404(
    monkeypatch,
    method,
    service_name,
    request_kwargs,
) -> None:
    def fake_operation(*args, **kwargs):
        raise course_service.CourseNotFoundError

    monkeypatch.setattr(course_service, service_name, fake_operation)
    client = make_client()

    response = client.request(
        method,
        f"/api/v1/courses/{COURSE_ID}",
        **request_kwargs,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Course not found"}


def test_update_course_supports_partial_updates(monkeypatch) -> None:
    captured = {}

    def fake_update(session, *, owner_id, course_id, payload):
        captured.update(
            owner_id=owner_id,
            course_id=course_id,
            fields=payload.model_dump(exclude_unset=True),
        )
        return make_course(description=None)

    monkeypatch.setattr(course_service, "update_course", fake_update)
    client = make_client()

    response = client.patch(
        f"/api/v1/courses/{COURSE_ID}",
        json={"description": None},
    )

    assert response.status_code == 200
    assert response.json()["description"] is None
    assert captured["owner_id"] == USER_ID
    assert captured["fields"] == {"description": None}


def test_update_course_rejects_empty_patch(monkeypatch) -> None:
    called = False

    def fake_update(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(course_service, "update_course", fake_update)
    client = make_client()

    response = client.patch(f"/api/v1/courses/{COURSE_ID}", json={})

    assert response.status_code == 422
    assert called is False


def test_delete_course_returns_no_content(monkeypatch) -> None:
    captured = {}

    def fake_delete(session, *, owner_id, course_id):
        captured.update(owner_id=owner_id, course_id=course_id)

    monkeypatch.setattr(course_service, "delete_course", fake_delete)
    client = make_client()

    response = client.delete(f"/api/v1/courses/{COURSE_ID}")

    assert response.status_code == 204
    assert response.content == b""
    assert captured == {"owner_id": USER_ID, "course_id": COURSE_ID}


def test_course_endpoints_require_authentication() -> None:
    client = make_client(authenticated=False)

    response = client.get("/api/v1/courses")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
