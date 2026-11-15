"""Ownership-aware entry persistence and library listing."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.models.entry import Entry
from app.models.entry_embedding import EntryEmbedding
from app.schemas.entry import (
    EntryCreate,
    EntryIndexStatus,
    EntryKind,
    EntryUpdate,
)
from app.services import course_service


class EntryNotFoundError(Exception):
    """Raised when an owner-scoped entry query finds no resource."""


class InvalidEntryCursorError(ValueError):
    """Raised when an entry-list cursor is malformed or unsupported."""


@dataclass(frozen=True)
class EntryCursor:
    created_at: datetime
    entry_id: UUID


@dataclass(frozen=True)
class EntrySummaryRecord:
    id: UUID
    course_id: UUID | None
    title: str
    kind: str
    statement: str
    topic: str | None
    index_status: str
    has_proof: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EntryListPage:
    items: list[EntrySummaryRecord]
    next_cursor: str | None


def create_entry(
    session: Session,
    *,
    owner_id: UUID,
    payload: EntryCreate,
) -> Entry:
    if payload.course_id is not None:
        course_service.get_course(
            session,
            owner_id=owner_id,
            course_id=payload.course_id,
        )

    entry = Entry(
        owner_id=owner_id,
        course_id=payload.course_id,
        title=payload.title,
        kind=payload.kind.value,
        statement=payload.statement,
        proof=payload.proof,
        topic=payload.topic,
        source_reference=payload.source_reference,
        index_status=EntryIndexStatus.PENDING.value,
    )
    session.add(entry)
    _commit(session)
    session.refresh(entry)
    return entry


def list_entries(
    session: Session,
    *,
    owner_id: UUID,
    kind: EntryKind | None = None,
    course_id: UUID | None = None,
    topic: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> EntryListPage:
    decoded_cursor = decode_entry_cursor(cursor) if cursor is not None else None

    statement = select(
        Entry.id,
        Entry.course_id,
        Entry.title,
        Entry.kind,
        Entry.statement,
        Entry.topic,
        Entry.index_status,
        Entry.proof.is_not(None).label("has_proof"),
        Entry.created_at,
        Entry.updated_at,
    ).where(Entry.owner_id == owner_id)

    if kind is not None:
        statement = statement.where(Entry.kind == kind.value)
    if course_id is not None:
        statement = statement.where(Entry.course_id == course_id)
    if topic is not None:
        statement = statement.where(Entry.topic == topic)
    if decoded_cursor is not None:
        statement = statement.where(
            or_(
                Entry.created_at < decoded_cursor.created_at,
                and_(
                    Entry.created_at == decoded_cursor.created_at,
                    Entry.id < decoded_cursor.entry_id,
                ),
            )
        )

    statement = statement.order_by(
        Entry.created_at.desc(),
        Entry.id.desc(),
    ).limit(limit + 1)

    rows = session.execute(statement).mappings().all()
    has_more = len(rows) > limit
    items = [_summary_from_row(row) for row in rows[:limit]]
    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = encode_entry_cursor(last_item.created_at, last_item.id)

    return EntryListPage(items=items, next_cursor=next_cursor)


def get_entry(
    session: Session,
    *,
    owner_id: UUID,
    entry_id: UUID,
) -> Entry:
    statement = select(Entry).where(
        Entry.id == entry_id,
        Entry.owner_id == owner_id,
    )
    entry = session.scalar(statement)
    if entry is None:
        raise EntryNotFoundError
    return entry


def update_entry(
    session: Session,
    *,
    owner_id: UUID,
    entry_id: UUID,
    payload: EntryUpdate,
) -> Entry:
    entry = get_entry(
        session,
        owner_id=owner_id,
        entry_id=entry_id,
    )

    if "course_id" in payload.model_fields_set and payload.course_id is not None:
        course_service.get_course(
            session,
            owner_id=owner_id,
            course_id=payload.course_id,
        )

    changes = payload.model_dump(exclude_unset=True)
    statement_changed = (
        "statement" in changes and changes["statement"] != entry.statement
    )

    try:
        for field_name, value in changes.items():
            if field_name == "kind" and value is not None:
                value = value.value
            setattr(entry, field_name, value)

        if statement_changed:
            entry.index_status = EntryIndexStatus.PENDING.value
            session.execute(
                delete(EntryEmbedding).where(EntryEmbedding.entry_id == entry.id)
            )

        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(entry)
    return entry


def delete_entry(
    session: Session,
    *,
    owner_id: UUID,
    entry_id: UUID,
) -> None:
    entry = get_entry(
        session,
        owner_id=owner_id,
        entry_id=entry_id,
    )
    session.delete(entry)
    _commit(session)


def encode_entry_cursor(created_at: datetime, entry_id: UUID) -> str:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("entry cursor timestamp must include a timezone")

    timestamp = created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    payload = json.dumps(
        {
            "v": 1,
            "created_at": timestamp,
            "id": str(entry_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_entry_cursor(cursor: str) -> EntryCursor:
    if not cursor or len(cursor) > 1_024:
        raise InvalidEntryCursorError("invalid entry cursor")

    try:
        padding = "=" * (-len(cursor) % 4)
        raw_payload = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw_payload.decode("utf-8"))

        if not isinstance(payload, dict) or set(payload) != {
            "v",
            "created_at",
            "id",
        }:
            raise ValueError
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError
        if not isinstance(payload["created_at"], str) or not isinstance(
            payload["id"],
            str,
        ):
            raise ValueError

        timestamp_source = payload["created_at"]
        if timestamp_source.endswith("Z"):
            timestamp_source = f"{timestamp_source[:-1]}+00:00"
        created_at = datetime.fromisoformat(timestamp_source)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        entry_id = UUID(payload["id"])
    except (
        AttributeError,
        binascii.Error,
        UnicodeDecodeError,
        TypeError,
        ValueError,
    ) as error:
        raise InvalidEntryCursorError("invalid entry cursor") from error

    return EntryCursor(
        created_at=created_at.astimezone(UTC),
        entry_id=entry_id,
    )


def _summary_from_row(row: RowMapping) -> EntrySummaryRecord:
    return EntrySummaryRecord(
        id=row["id"],
        course_id=row["course_id"],
        title=row["title"],
        kind=row["kind"],
        statement=row["statement"],
        topic=row["topic"],
        index_status=row["index_status"],
        has_proof=row["has_proof"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
