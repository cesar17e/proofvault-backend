"""Reliable statement indexing and embedding persistence."""

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingBatch,
    EmbeddingProvider,
    EmbeddingProviderError,
    InvalidEmbeddingResponseError,
)
from app.models.entry import Entry
from app.models.entry_embedding import EntryEmbedding
from app.schemas.entry import EntryIndexStatus


logger = logging.getLogger(__name__)


class IndexingEntryNotFoundError(Exception):
    """Raised when an owner-scoped indexing lookup finds no entry."""


class IndexingConfigurationError(ValueError):
    """Raised when a provider cannot satisfy the database vector contract."""


class IndexingOutcome(StrEnum):
    INDEXED = "indexed"
    SKIPPED = "skipped"
    FAILED = "failed"
    STALE = "stale"


@dataclass(frozen=True)
class IndexingResult:
    entry_id: UUID
    outcome: IndexingOutcome
    index_status: EntryIndexStatus
    content_hash: str
    provider: str
    model: str
    duration_ms: float
    total_tokens: int | None = None
    failure_type: str | None = None


@dataclass(frozen=True)
class _FinalizationResult:
    applied: bool
    index_status: EntryIndexStatus


def statement_content_hash(statement: str) -> str:
    """Fingerprint the exact stored UTF-8 statement without normalization."""
    if not isinstance(statement, str):
        raise TypeError("statement must be a string")
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def index_entry(
    session: Session,
    *,
    owner_id: UUID,
    entry_id: UUID,
    provider: EmbeddingProvider,
    before_provider_call: Callable[[], None] | None = None,
) -> IndexingResult:
    """Ensure one entry has a current statement embedding."""
    _validate_provider(provider)

    entry, existing_embedding = _load_entry_and_embedding(
        session,
        owner_id=owner_id,
        entry_id=entry_id,
    )
    statement_source = entry.statement
    content_hash = statement_content_hash(statement_source)

    if _embedding_is_current(
        existing_embedding,
        content_hash=content_hash,
        provider=provider,
    ):
        if entry.index_status != EntryIndexStatus.READY.value:
            entry.index_status = EntryIndexStatus.READY.value

        _commit(session)

        result = IndexingResult(
            entry_id=entry_id,
            outcome=IndexingOutcome.SKIPPED,
            index_status=EntryIndexStatus.READY,
            content_hash=content_hash,
            provider=provider.name,
            model=provider.model,
            duration_ms=0.0,
        )
        _log_result(result)
        return result

    entry.index_status = EntryIndexStatus.PENDING.value
    # This timestamp is also the V1 signal that a pending entry may still be
    # actively indexing. It lets repair tooling avoid recently started work.
    entry.updated_at = datetime.now(UTC)
    if existing_embedding is not None:
        session.execute(
            delete(EntryEmbedding).where(
                EntryEmbedding.entry_id == entry_id
            )
        )
    # End the preparation transaction before the external provider call.
    _commit(session)

    started_at = time.perf_counter()
    try:
        if before_provider_call is not None:
            before_provider_call()
        batch = provider.embed_documents([statement_source])
        vector = _single_embedding(batch)
    except EmbeddingProviderError as error:
        duration_ms = _elapsed_ms(started_at)
        finalization = _mark_failed(
            session,
            owner_id=owner_id,
            entry_id=entry_id,
            expected_content_hash=content_hash,
        )
        result = IndexingResult(
            entry_id=entry_id,
            outcome=(
                IndexingOutcome.FAILED
                if finalization.applied
                else IndexingOutcome.STALE
            ),
            index_status=finalization.index_status,
            content_hash=content_hash,
            provider=provider.name,
            model=provider.model,
            duration_ms=duration_ms,
            failure_type=error.error_type or type(error).__name__,
        )
        _log_result(result)
        return result

    duration_ms = _elapsed_ms(started_at)
    finalization = _store_embedding(
        session,
        owner_id=owner_id,
        entry_id=entry_id,
        vector=vector,
        provider=provider,
        content_hash=content_hash,
    )
    result = IndexingResult(
        entry_id=entry_id,
        outcome=(
            IndexingOutcome.INDEXED
            if finalization.applied
            else IndexingOutcome.STALE
        ),
        index_status=finalization.index_status,
        content_hash=content_hash,
        provider=provider.name,
        model=provider.model,
        duration_ms=duration_ms,
        total_tokens=batch.total_tokens,
    )
    _log_result(result)
    return result


def _validate_provider(provider: EmbeddingProvider) -> None:
    if provider.dimensions != EMBEDDING_DIMENSIONS:
        raise IndexingConfigurationError(
            f"Embedding provider must return {EMBEDDING_DIMENSIONS} dimensions"
        )
    if not provider.name.strip() or len(provider.name) > 50:
        raise IndexingConfigurationError(
            "Embedding provider name must contain 1 to 50 characters"
        )
    if not provider.model.strip() or len(provider.model) > 100:
        raise IndexingConfigurationError(
            "Embedding model name must contain 1 to 100 characters"
        )


def _load_entry_and_embedding(
    session: Session,
    *,
    owner_id: UUID,
    entry_id: UUID,
) -> tuple[Entry, EntryEmbedding | None]:
    statement = (
        select(Entry, EntryEmbedding)
        .outerjoin(
            EntryEmbedding,
            EntryEmbedding.entry_id == Entry.id,
        )
        .where(
            Entry.id == entry_id,
            Entry.owner_id == owner_id,
        )
        .with_for_update(of=Entry)
        .execution_options(populate_existing=True)
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        session.rollback()
        raise IndexingEntryNotFoundError
    entry, embedding = row
    return entry, embedding


def _embedding_is_current(
    embedding: EntryEmbedding | None,
    *,
    content_hash: str,
    provider: EmbeddingProvider,
) -> bool:
    return (
        embedding is not None
        and embedding.content_hash == content_hash
        and embedding.provider == provider.name
        and embedding.model == provider.model
    )


def _single_embedding(batch: EmbeddingBatch) -> tuple[float, ...]:
    if len(batch.embeddings) != 1:
        raise InvalidEmbeddingResponseError(
            "Embedding provider returned an unexpected number of vectors"
        )
    vector = batch.embeddings[0]
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise InvalidEmbeddingResponseError(
            f"Embedding vector must contain {EMBEDDING_DIMENSIONS} values"
        )
    return vector


def _mark_failed(
    session: Session,
    *,
    owner_id: UUID,
    entry_id: UUID,
    expected_content_hash: str,
) -> _FinalizationResult:
    entry = _load_entry_for_update(
        session,
        owner_id=owner_id,
        entry_id=entry_id,
    )
    if statement_content_hash(entry.statement) != expected_content_hash:
        _commit(session)
        return _FinalizationResult(
            applied=False,
            index_status=EntryIndexStatus(entry.index_status),
        )

    entry.index_status = EntryIndexStatus.FAILED.value
    _commit(session)
    return _FinalizationResult(
        applied=True,
        index_status=EntryIndexStatus.FAILED,
    )


def _store_embedding(
    session: Session,
    *,
    owner_id: UUID,
    entry_id: UUID,
    vector: tuple[float, ...],
    provider: EmbeddingProvider,
    content_hash: str,
) -> _FinalizationResult:
    entry = _load_entry_for_update(
        session,
        owner_id=owner_id,
        entry_id=entry_id,
    )
    if statement_content_hash(entry.statement) != content_hash:
        _commit(session)
        return _FinalizationResult(
            applied=False,
            index_status=EntryIndexStatus(entry.index_status),
        )

    insert_statement = insert(EntryEmbedding).values(
        entry_id=entry_id,
        embedding=list(vector),
        provider=provider.name,
        model=provider.model,
        content_hash=content_hash,
    )
    upsert_statement = insert_statement.on_conflict_do_update(
        index_elements=[EntryEmbedding.entry_id],
        set_={
            "embedding": insert_statement.excluded.embedding,
            "provider": insert_statement.excluded.provider,
            "model": insert_statement.excluded.model,
            "content_hash": insert_statement.excluded.content_hash,
            "created_at": func.now(),
        },
    )
    session.execute(upsert_statement)
    entry.index_status = EntryIndexStatus.READY.value
    _commit(session)
    return _FinalizationResult(
        applied=True,
        index_status=EntryIndexStatus.READY,
    )


def _load_entry_for_update(
    session: Session,
    *,
    owner_id: UUID,
    entry_id: UUID,
) -> Entry:
    statement = (
        select(Entry)
        .where(
            Entry.id == entry_id,
            Entry.owner_id == owner_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    entry = session.scalar(statement)
    if entry is None:
        session.rollback()
        raise IndexingEntryNotFoundError
    return entry


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1_000, 3)


def _log_result(result: IndexingResult) -> None:
    log_method = (
        logger.warning
        if result.outcome is IndexingOutcome.FAILED
        else logger.info
    )
    log_method(
        "Entry indexing %s",
        result.outcome.value,
        extra={
            "entry_id": str(result.entry_id),
            "indexing_outcome": result.outcome.value,
            "index_status": result.index_status.value,
            "embedding_provider": result.provider,
            "embedding_model": result.model,
            "embedding_duration_ms": result.duration_ms,
            "embedding_total_tokens": result.total_tokens,
            "embedding_failure_type": result.failure_type,
        },
    )
