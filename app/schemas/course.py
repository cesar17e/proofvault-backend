"""Request and response contracts for ProofVault courses."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)


CourseName = Annotated[str, StringConstraints(max_length=200)]
CourseDescription = Annotated[str, StringConstraints(max_length=5_000)]


class CourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CourseName
    description: CourseDescription | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("course name must not be blank")
        return value


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CourseName | None = None
    description: CourseDescription | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("course name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> "CourseUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("course name may not be null")
        return self


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class CourseListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CourseResponse]
