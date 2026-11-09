from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Course(TimestampMixin, Base):
    __tablename__ = "courses"

    __table_args__ = (
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_courses_name_not_blank",
        ),
        UniqueConstraint(
            "id",
            "owner_id",
            name="uq_courses_id_owner",
        ),
        Index("ix_courses_owner_id", "owner_id"),
        {"schema": "proofvault"},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )