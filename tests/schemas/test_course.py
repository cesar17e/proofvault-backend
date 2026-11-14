from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.course import CourseCreate, CourseResponse, CourseUpdate


COURSE_ID = UUID("123e4567-e89b-12d3-a456-426614174000")


def test_course_create_preserves_valid_source() -> None:
    payload = CourseCreate(
        name="  Real Analysis  ",
        description="Limits, sequences, and continuity.",
    )

    assert payload.name == "  Real Analysis  "


@pytest.mark.parametrize("name", ["", "   ", "\n\t"])
def test_course_name_must_not_be_blank(name: str) -> None:
    with pytest.raises(ValidationError):
        CourseCreate(name=name)


def test_course_request_rejects_server_controlled_fields() -> None:
    with pytest.raises(ValidationError):
        CourseCreate(
            name="Topology",
            owner_id="223e4567-e89b-12d3-a456-426614174000",
        )


def test_course_update_requires_a_field_and_non_null_name() -> None:
    with pytest.raises(ValidationError):
        CourseUpdate()

    with pytest.raises(ValidationError):
        CourseUpdate(name=None)

    assert CourseUpdate(description=None).model_fields_set == {"description"}


def test_course_response_reads_orm_attributes_without_owner_id() -> None:
    now = datetime.now(UTC)
    response = CourseResponse.model_validate(
        SimpleNamespace(
            id=COURSE_ID,
            owner_id=UUID("223e4567-e89b-12d3-a456-426614174000"),
            name="Real Analysis",
            description=None,
            created_at=now,
            updated_at=now,
        )
    )

    assert response.id == COURSE_ID
    assert "owner_id" not in response.model_dump()
