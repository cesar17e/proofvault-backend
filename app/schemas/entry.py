"""Request and response contracts for mathematical library entries."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.validation import validate_markdown_latex


EntryTitle = Annotated[str, StringConstraints(max_length=200)]
StatementSource = Annotated[str, StringConstraints(max_length=50_000)]
ProofSource = Annotated[str, StringConstraints(max_length=100_000)]
EntryTopic = Annotated[str, StringConstraints(max_length=100)]
SourceReference = Annotated[str, StringConstraints(max_length=2_000)]


class EntryKind(StrEnum):
    THEOREM = "theorem"
    PROBLEM = "problem"


class EntryIndexStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class EntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: UUID | None = None
    title: EntryTitle
    kind: EntryKind
    statement: StatementSource
    proof: ProofSource | None = None
    topic: EntryTopic | None = None
    source_reference: SourceReference | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("entry title must not be blank")
        return value

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("entry statement must not be blank")
        return validate_markdown_latex(value)

    @field_validator("proof")
    @classmethod
    def validate_proof(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_markdown_latex(value)


class EntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: UUID | None = None
    title: EntryTitle | None = None
    kind: EntryKind | None = None
    statement: StatementSource | None = None
    proof: ProofSource | None = None
    topic: EntryTopic | None = None
    source_reference: SourceReference | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("entry title must not be blank")
        return value

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("entry statement must not be blank")
        return validate_markdown_latex(value)

    @field_validator("proof")
    @classmethod
    def validate_proof(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_markdown_latex(value)

    @model_validator(mode="after")
    def validate_patch(self) -> "EntryUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")

        for field_name in ("title", "kind", "statement"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"entry {field_name} may not be null")
        return self


class EntryDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    course_id: UUID | None
    title: str
    kind: EntryKind
    statement: str
    proof: str | None
    topic: str | None
    source_reference: str | None
    index_status: EntryIndexStatus
    created_at: datetime
    updated_at: datetime


class EntrySummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    course_id: UUID | None
    title: str
    kind: EntryKind
    statement: str
    topic: str | None
    index_status: EntryIndexStatus
    has_proof: bool
    created_at: datetime
    updated_at: datetime


class EntryListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[EntrySummaryResponse]
    next_cursor: str | None
