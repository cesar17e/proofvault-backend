from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.schemas.course import CourseCreate, CourseUpdate
from app.services import course_service


OWNER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
OTHER_OWNER_ID = UUID("223e4567-e89b-12d3-a456-426614174000")
COURSE_ID = UUID("323e4567-e89b-12d3-a456-426614174000")


def make_session() -> MagicMock:
    return MagicMock(spec=Session)


def test_create_course_uses_authenticated_owner_and_commits() -> None:
    session = make_session()

    course = course_service.create_course(
        session,
        owner_id=OWNER_ID,
        payload=CourseCreate(name="Real Analysis", description="Sequences"),
    )

    assert course.owner_id == OWNER_ID
    assert course.name == "Real Analysis"
    assert course.description == "Sequences"
    session.add.assert_called_once_with(course)
    session.commit.assert_called_once_with()
    session.refresh.assert_called_once_with(course)


def test_course_lookup_scopes_id_and_owner_in_one_query() -> None:
    session = make_session()
    stored_course = SimpleNamespace(id=COURSE_ID, owner_id=OWNER_ID)
    session.scalar.return_value = stored_course

    result = course_service.get_course(
        session,
        owner_id=OWNER_ID,
        course_id=COURSE_ID,
    )

    assert result is stored_course
    statement = session.scalar.call_args.args[0]
    sql = str(statement)
    assert "proofvault.courses.id" in sql
    assert "proofvault.courses.owner_id" in sql
    assert " AND " in sql
    assert COURSE_ID in statement.compile().params.values()
    assert OWNER_ID in statement.compile().params.values()


def test_missing_and_foreign_course_have_same_service_result() -> None:
    session = make_session()
    session.scalar.return_value = None

    with pytest.raises(course_service.CourseNotFoundError):
        course_service.get_course(
            session,
            owner_id=OTHER_OWNER_ID,
            course_id=COURSE_ID,
        )


def test_list_courses_is_owner_scoped_and_stably_ordered() -> None:
    session = make_session()
    session.scalars.return_value.all.return_value = []

    assert course_service.list_courses(session, owner_id=OWNER_ID) == []

    statement = session.scalars.call_args.args[0]
    sql = str(statement)
    assert "proofvault.courses.owner_id" in sql
    assert "ORDER BY proofvault.courses.name ASC, proofvault.courses.id ASC" in sql
    assert OWNER_ID in statement.compile().params.values()


def test_update_course_applies_only_supplied_fields() -> None:
    session = make_session()
    stored_course = SimpleNamespace(
        id=COURSE_ID,
        owner_id=OWNER_ID,
        name="Analysis",
        description="Old description",
    )
    session.scalar.return_value = stored_course

    result = course_service.update_course(
        session,
        owner_id=OWNER_ID,
        course_id=COURSE_ID,
        payload=CourseUpdate(description=None),
    )

    assert result is stored_course
    assert stored_course.name == "Analysis"
    assert stored_course.description is None
    session.commit.assert_called_once_with()
    session.refresh.assert_called_once_with(stored_course)


def test_delete_course_uses_owner_scoped_lookup() -> None:
    session = make_session()
    stored_course = SimpleNamespace(id=COURSE_ID, owner_id=OWNER_ID)
    session.scalar.return_value = stored_course

    course_service.delete_course(
        session,
        owner_id=OWNER_ID,
        course_id=COURSE_ID,
    )

    session.delete.assert_called_once_with(stored_course)
    session.commit.assert_called_once_with()


def test_failed_commit_rolls_back() -> None:
    session = make_session()
    session.commit.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        course_service.create_course(
            session,
            owner_id=OWNER_ID,
            payload=CourseCreate(name="Topology"),
        )

    session.rollback.assert_called_once_with()
    session.refresh.assert_not_called()
