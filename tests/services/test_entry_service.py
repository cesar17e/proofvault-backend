from types import SimpleNamespace
from unittest.mock import MagicMock
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.schemas.entry import EntryCreate, EntryKind, EntryUpdate
from app.services import course_service, entry_service


OWNER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
OTHER_OWNER_ID = UUID("223e4567-e89b-12d3-a456-426614174000")
ENTRY_ID = UUID("323e4567-e89b-12d3-a456-426614174000")
COURSE_ID = UUID("423e4567-e89b-12d3-a456-426614174000")
SECOND_ENTRY_ID = UUID("523e4567-e89b-12d3-a456-426614174000")
THIRD_ENTRY_ID = UUID("623e4567-e89b-12d3-a456-426614174000")
CREATED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


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


def make_summary_row(
    entry_id: UUID,
    created_at: datetime,
    *,
    has_proof: bool = True,
) -> dict:
    return {
        "id": entry_id,
        "course_id": COURSE_ID,
        "title": f"Entry {entry_id}",
        "kind": "theorem",
        "statement": "$x=x$",
        "topic": "Sequences",
        "index_status": "pending",
        "has_proof": has_proof,
        "created_at": created_at,
        "updated_at": created_at,
    }


def make_stored_entry(**overrides) -> SimpleNamespace:
    values = {
        "id": ENTRY_ID,
        "owner_id": OWNER_ID,
        "course_id": COURSE_ID,
        "title": "Convergent sequences are bounded",
        "kind": "theorem",
        "statement": "If $a_n \\to L$, then $(a_n)$ is bounded.",
        "proof": "Original proof",
        "topic": "Sequences",
        "source_reference": "Lecture 3",
        "index_status": "ready",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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


def test_list_entries_is_filtered_owner_scoped_and_uses_limit_plus_one() -> None:
    session = make_session()
    rows = [
        make_summary_row(ENTRY_ID, CREATED_AT),
        make_summary_row(SECOND_ENTRY_ID, CREATED_AT - timedelta(minutes=1)),
        make_summary_row(THIRD_ENTRY_ID, CREATED_AT - timedelta(minutes=2)),
    ]
    session.execute.return_value.mappings.return_value.all.return_value = rows

    page = entry_service.list_entries(
        session,
        owner_id=OWNER_ID,
        kind=EntryKind.THEOREM,
        course_id=COURSE_ID,
        topic="Sequences",
        limit=2,
    )

    assert [item.id for item in page.items] == [ENTRY_ID, SECOND_ENTRY_ID]
    assert page.items[0].has_proof is True
    assert page.next_cursor is not None
    decoded_cursor = entry_service.decode_entry_cursor(page.next_cursor)
    assert decoded_cursor.entry_id == SECOND_ENTRY_ID
    assert decoded_cursor.created_at == CREATED_AT - timedelta(minutes=1)

    statement = session.execute.call_args.args[0]
    sql = str(statement)
    params = statement.compile().params.values()
    assert "proofvault.entries.owner_id" in sql
    assert "proofvault.entries.kind" in sql
    assert "proofvault.entries.course_id" in sql
    assert "proofvault.entries.topic" in sql
    assert "proofvault.entries.proof IS NOT NULL AS has_proof" in sql
    assert "ORDER BY proofvault.entries.created_at DESC" in sql
    assert "proofvault.entries.id DESC" in sql
    assert OWNER_ID in params
    assert COURSE_ID in params
    assert "theorem" in params
    assert "Sequences" in params
    assert 3 in params


def test_list_entries_returns_no_cursor_without_an_extra_row() -> None:
    session = make_session()
    session.execute.return_value.mappings.return_value.all.return_value = [
        make_summary_row(ENTRY_ID, CREATED_AT, has_proof=False)
    ]

    page = entry_service.list_entries(session, owner_id=OWNER_ID, limit=2)

    assert len(page.items) == 1
    assert page.items[0].has_proof is False
    assert page.next_cursor is None


def test_list_entries_applies_keyset_cursor_after_ownership_condition() -> None:
    session = make_session()
    session.execute.return_value.mappings.return_value.all.return_value = []
    cursor = entry_service.encode_entry_cursor(CREATED_AT, ENTRY_ID)

    page = entry_service.list_entries(
        session,
        owner_id=OWNER_ID,
        cursor=cursor,
    )

    assert page.items == []
    assert page.next_cursor is None
    statement = session.execute.call_args.args[0]
    sql = str(statement)
    params = statement.compile().params.values()
    assert "proofvault.entries.owner_id" in sql
    assert "proofvault.entries.created_at <" in sql
    assert "proofvault.entries.created_at =" in sql
    assert "proofvault.entries.id <" in sql
    assert OWNER_ID in params
    assert ENTRY_ID in params


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!",
        "e30",
        entry_service.encode_entry_cursor(CREATED_AT, ENTRY_ID) + "extra",
        "a" * 1_025,
    ],
)
def test_invalid_entry_cursor_is_rejected_before_query(cursor: str) -> None:
    session = make_session()

    with pytest.raises(entry_service.InvalidEntryCursorError):
        entry_service.list_entries(
            session,
            owner_id=OWNER_ID,
            cursor=cursor,
        )

    session.execute.assert_not_called()


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


def test_proof_only_update_preserves_statement_index(monkeypatch) -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry
    course_lookup = MagicMock()
    monkeypatch.setattr(course_service, "get_course", course_lookup)

    result = entry_service.update_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        payload=EntryUpdate(proof="  Revised proof using $\\varepsilon$.  "),
    )

    assert result is stored_entry
    assert stored_entry.proof == "  Revised proof using $\\varepsilon$.  "
    assert stored_entry.index_status == "ready"
    course_lookup.assert_not_called()
    session.execute.assert_not_called()
    session.commit.assert_called_once_with()
    session.refresh.assert_called_once_with(stored_entry)


def test_metadata_update_does_not_invalidate_statement_embedding() -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry

    entry_service.update_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        payload=EntryUpdate(
            title="A problem about bounded sequences",
            kind="problem",
            topic=None,
            source_reference=None,
        ),
    )

    assert stored_entry.title == "A problem about bounded sequences"
    assert stored_entry.kind == "problem"
    assert stored_entry.topic is None
    assert stored_entry.source_reference is None
    assert stored_entry.index_status == "ready"
    session.execute.assert_not_called()


def test_statement_update_invalidates_embedding_in_same_transaction() -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry
    revised_statement = "  Every convergent real sequence is bounded.  "

    result = entry_service.update_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        payload=EntryUpdate(statement=revised_statement),
    )

    assert result.statement == revised_statement
    assert result.index_status == "pending"
    delete_statement = session.execute.call_args.args[0]
    sql = str(delete_statement)
    assert "DELETE FROM proofvault.entry_embeddings" in sql
    assert "entry_embeddings.entry_id" in sql
    assert ENTRY_ID in delete_statement.compile().params.values()
    session.commit.assert_called_once_with()
    session.refresh.assert_called_once_with(stored_entry)


def test_resubmitting_identical_statement_does_not_invalidate_embedding() -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry

    entry_service.update_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        payload=EntryUpdate(statement=stored_entry.statement),
    )

    assert stored_entry.index_status == "ready"
    session.execute.assert_not_called()


def test_course_reassignment_verifies_ownership_before_mutation(monkeypatch) -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry
    course_lookup = MagicMock(return_value=SimpleNamespace(id=SECOND_ENTRY_ID))
    monkeypatch.setattr(course_service, "get_course", course_lookup)

    entry_service.update_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        payload=EntryUpdate(course_id=SECOND_ENTRY_ID),
    )

    course_lookup.assert_called_once_with(
        session,
        owner_id=OWNER_ID,
        course_id=SECOND_ENTRY_ID,
    )
    assert stored_entry.course_id == SECOND_ENTRY_ID


def test_foreign_course_reassignment_leaves_entry_unchanged(monkeypatch) -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry

    def reject_course(*args, **kwargs):
        raise course_service.CourseNotFoundError

    monkeypatch.setattr(course_service, "get_course", reject_course)

    with pytest.raises(course_service.CourseNotFoundError):
        entry_service.update_entry(
            session,
            owner_id=OWNER_ID,
            entry_id=ENTRY_ID,
            payload=EntryUpdate(course_id=SECOND_ENTRY_ID),
        )

    assert stored_entry.course_id == COURSE_ID
    session.commit.assert_not_called()


def test_course_can_be_cleared_without_lookup(monkeypatch) -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry
    course_lookup = MagicMock()
    monkeypatch.setattr(course_service, "get_course", course_lookup)

    entry_service.update_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        payload=EntryUpdate(course_id=None),
    )

    course_lookup.assert_not_called()
    assert stored_entry.course_id is None


def test_failed_update_rolls_back_without_refresh() -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry
    session.commit.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        entry_service.update_entry(
            session,
            owner_id=OWNER_ID,
            entry_id=ENTRY_ID,
            payload=EntryUpdate(proof="Revised proof"),
        )

    session.rollback.assert_called_once_with()
    session.refresh.assert_not_called()


def test_delete_entry_uses_owner_scoped_lookup_and_commits() -> None:
    session = make_session()
    stored_entry = make_stored_entry()
    session.scalar.return_value = stored_entry

    entry_service.delete_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
    )

    session.delete.assert_called_once_with(stored_entry)
    session.commit.assert_called_once_with()


def test_failed_delete_rolls_back() -> None:
    session = make_session()
    session.scalar.return_value = make_stored_entry()
    session.commit.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        entry_service.delete_entry(
            session,
            owner_id=OWNER_ID,
            entry_id=ENTRY_ID,
        )

    session.rollback.assert_called_once_with()


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
