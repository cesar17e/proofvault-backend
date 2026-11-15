from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.schemas.entry import EntryCreate
from app.services import course_service, entry_service


OWNER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
OTHER_OWNER_ID = UUID("223e4567-e89b-12d3-a456-426614174000")
ENTRY_ID = UUID("323e4567-e89b-12d3-a456-426614174000")
COURSE_ID = UUID("423e4567-e89b-12d3-a456-426614174000")


def make_session() -> MagicMock:
    return MagicMock(spec=Session)


def make_payload(*, course_id: UUID | None = None) -> EntryCreate:
    return EntryCreate(
        course_id=course_id,
        title="Convergent sequences are bounded",
        kind="theorem",
        statement="  If $a_n \\to L$, then $(a_n)$ is bounded.  ",
        proof="Choose $N$ such that $|a_n-L|<1$ for $n\\ge N$.",
        topic="Sequences",
        source_reference="Lecture 3",
    )


def test_create_entry_without_course_uses_authenticated_owner(monkeypatch) -> None:
    session = make_session()
    course_lookup = MagicMock()
    monkeypatch.setattr(course_service, "get_course", course_lookup)
    payload = make_payload()

    entry = entry_service.create_entry(
        session,
        owner_id=OWNER_ID,
        payload=payload,
    )

    course_lookup.assert_not_called()
    assert entry.owner_id == OWNER_ID
    assert entry.course_id is None
    assert entry.statement == payload.statement
    assert entry.proof == payload.proof
    assert entry.index_status == "pending"
    session.add.assert_called_once_with(entry)
    session.commit.assert_called_once_with()
    session.refresh.assert_called_once_with(entry)


def test_create_entry_verifies_course_ownership(monkeypatch) -> None:
    session = make_session()
    course_lookup = MagicMock(return_value=SimpleNamespace(id=COURSE_ID))
    monkeypatch.setattr(course_service, "get_course", course_lookup)
    payload = make_payload(course_id=COURSE_ID)

    entry_service.create_entry(
        session,
        owner_id=OWNER_ID,
        payload=payload,
    )

    course_lookup.assert_called_once_with(
        session,
        owner_id=OWNER_ID,
        course_id=COURSE_ID,
    )


def test_foreign_or_missing_course_prevents_entry_creation(monkeypatch) -> None:
    session = make_session()

    def reject_course(*args, **kwargs):
        raise course_service.CourseNotFoundError

    monkeypatch.setattr(course_service, "get_course", reject_course)

    with pytest.raises(course_service.CourseNotFoundError):
        entry_service.create_entry(
            session,
            owner_id=OTHER_OWNER_ID,
            payload=make_payload(course_id=COURSE_ID),
        )

    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_entry_lookup_scopes_id_and_owner_in_one_query() -> None:
    session = make_session()
    stored_entry = SimpleNamespace(id=ENTRY_ID, owner_id=OWNER_ID)
    session.scalar.return_value = stored_entry

    result = entry_service.get_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
    )

    assert result is stored_entry
    statement = session.scalar.call_args.args[0]
    sql = str(statement)
    assert "proofvault.entries.id" in sql
    assert "proofvault.entries.owner_id" in sql
    assert " AND " in sql
    assert ENTRY_ID in statement.compile().params.values()
    assert OWNER_ID in statement.compile().params.values()


def test_missing_and_foreign_entry_have_same_service_result() -> None:
    session = make_session()
    session.scalar.return_value = None

    with pytest.raises(entry_service.EntryNotFoundError):
        entry_service.get_entry(
            session,
            owner_id=OTHER_OWNER_ID,
            entry_id=ENTRY_ID,
        )


def test_failed_entry_commit_rolls_back() -> None:
    session = make_session()
    session.commit.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        entry_service.create_entry(
            session,
            owner_id=OWNER_ID,
            payload=make_payload(),
        )

    session.rollback.assert_called_once_with()
    session.refresh.assert_not_called()
