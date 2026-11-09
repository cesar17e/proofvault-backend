from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EntryEmbedding(Base):
    __tablename__ = "entry_embeddings"

    __table_args__ = (
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_entry_embeddings_content_hash",
        ),
        {"schema": "proofvault"},
    )

    entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "proofvault.entries.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    embedding: Mapped[list[float]] = mapped_column(
        VECTOR(1024),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )