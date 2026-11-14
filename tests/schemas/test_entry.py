from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.entry import (
    EntryCreate,
    EntryDetailResponse,
    EntryIndexStatus,
    EntryKind,
    EntryUpdate,
)


ENTRY_ID = UUID("123e4567-e89b-12d3-a456-426614174000")


def test_entry_create_preserves_mathematical_source_exactly() -> None:
    statement = "  Suppose $a_n \\to L$.\n\nThen $(a_n)$ is bounded.  "
    proof = "Choose $N$ such that $|a_n-L|<1$ whenever $n\\ge N$."

    payload = EntryCreate(
        title="Convergent sequences are bounded",
        kind="theorem",
        statement=statement,
        proof=proof,
        topic="Sequences",
    )

    assert payload.statement == statement
    assert payload.proof == proof
    assert payload.kind is EntryKind.THEOREM


@pytest.mark.parametrize("field", ["title", "statement"])
def test_required_entry_text_must_not_be_blank(field: str) -> None:
    data = {
        "title": "A theorem",
        "kind": "theorem",
        "statement": "$x=x$",
    }
    data[field] = "   "

    with pytest.raises(ValidationError):
        EntryCreate(**data)


def test_entry_create_rejects_invalid_math_and_server_fields() -> None:
    with pytest.raises(ValidationError):
        EntryCreate(
            title="Unsafe",
            kind="problem",
            statement=r"$\input{file}$",
            owner_id="223e4567-e89b-12d3-a456-426614174000",
            index_status="ready",
        )


def test_entry_limits_are_enforced() -> None:
    with pytest.raises(ValidationError):
        EntryCreate(
            title="A" * 201,
            kind="theorem",
            statement="$x=x$",
        )

    with pytest.raises(ValidationError):
        EntryCreate(
            title="A theorem",
            kind="theorem",
            statement="x" * 50_001,
        )


def test_entry_update_requires_a_field_and_protects_required_fields() -> None:
    with pytest.raises(ValidationError):
        EntryUpdate()

    for field_name in ("title", "kind", "statement"):
        with pytest.raises(ValidationError):
            EntryUpdate(**{field_name: None})


def test_entry_update_allows_clearing_nullable_fields() -> None:
    payload = EntryUpdate(
        course_id=None,
        proof=None,
        topic=None,
        source_reference=None,
    )

    assert payload.model_fields_set == {
        "course_id",
        "proof",
        "topic",
        "source_reference",
    }


def test_entry_update_validates_only_supplied_mathematical_content() -> None:
    payload = EntryUpdate(proof="A proof using $x^2\\ge 0$.")
    assert payload.proof == "A proof using $x^2\\ge 0$."

    with pytest.raises(ValidationError):
        EntryUpdate(statement="$$not closed")


def test_entry_detail_response_reads_orm_attributes_without_owner_id() -> None:
    now = datetime.now(UTC)
    response = EntryDetailResponse.model_validate(
        SimpleNamespace(
            id=ENTRY_ID,
            owner_id=UUID("223e4567-e89b-12d3-a456-426614174000"),
            course_id=None,
            title="A theorem",
            kind="theorem",
            statement="$x=x$",
            proof=None,
            topic=None,
            source_reference=None,
            index_status="pending",
            created_at=now,
            updated_at=now,
        )
    )

    assert response.kind is EntryKind.THEOREM
    assert response.index_status is EntryIndexStatus.PENDING
    assert "owner_id" not in response.model_dump()
