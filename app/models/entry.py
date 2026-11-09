from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Entry(TimestampMixin, Base):
    __tablename__ = "entries"

    __table_args__ = (
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_entries_title_not_blank",
        ),
        CheckConstraint(
            "length(trim(statement)) > 0",
            name="ck_entries_statement_not_blank",
        ),
        CheckConstraint(
            "kind IN ('theorem', 'problem')",
            name="ck_entries_kind",
        ),
        CheckConstraint(
            "index_status IN ('pending', 'ready', 'failed')",
            name="ck_entries_index_status",
        ),
        ForeignKeyConstraint(
            ["course_id", "owner_id"],
            [
                "proofvault.courses.id",
                "proofvault.courses.owner_id",
            ],
            name="fk_entries_course_owner",
            ondelete="SET NULL (course_id)",
        ),
        Index(
            "ix_entries_owner_created_id",
            "owner_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_entries_owner_course",
            "owner_id",
            "course_id",
        ),
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

    course_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    statement: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    proof: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    topic: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    source_reference: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    index_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'"),
    )