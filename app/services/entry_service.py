"""Ownership-aware entry creation and detail retrieval."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entry import Entry
from app.schemas.entry import EntryCreate, EntryIndexStatus
from app.services import course_service


class EntryNotFoundError(Exception):
    """Raised when an owner-scoped entry query finds no resource."""


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


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
