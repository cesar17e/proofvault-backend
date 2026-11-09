from datetime import datetime

from sqlalchemy import Column, DateTime, Table, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# Reference only: Supabase owns and manages this existing table.
auth_users = Table(
    "users",
    Base.metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    schema="auth",
    info={"externally_managed": True},
)