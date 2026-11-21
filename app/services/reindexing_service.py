"""Internal inspection and repair orchestration for statement embeddings."""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.embeddings import EmbeddingProvider
from app.models.entry import Entry
from app.models.entry_embedding import EntryEmbedding
from app.services import indexing_service


DEFAULT_BATCH_LIMIT = 20
MAX_BATCH_LIMIT = 100
DEFAULT_MIN_INTERVAL_SECONDS = 30.0
DEFAULT_PENDING_MIN_AGE_SECONDS = 300.0


class ReindexingConfigurationError(ValueError):
    """Raised when repair limits or pacing settings are unsafe."""


class ReindexingEntryNotFoundError(Exception):
    """Raised when an owner-scoped targeted entry does not exist."""


class RepairReason(StrEnum):
    FAILED_STATUS = "failed_status"
    STALE_PENDING = "stale_pending"
    MISSING_EMBEDDING = "missing_embedding"
    CONTENT_HASH_MISMATCH = "content_hash_mismatch"
    PROVIDER_MISMATCH = "provider_mismatch"
    MODEL_MISMATCH = "model_mismatch"


@dataclass(frozen=True)
class RepairCandidate:
    entry_id: UUID
    owner_id: UUID
    reasons: tuple[RepairReason, ...]
    recent_pending: bool = False


@dataclass(frozen=True)
class RepairInspection:
    total_inspected: int
    eligible_entries: int
    candidates: tuple[RepairCandidate, ...]
    deferred_recent_pending: int


@dataclass(frozen=True)
class ReindexingReport:
    dry_run: bool
    total_inspected: int
    eligible_entries: int
    selected_entries: int
    indexed_successfully: int
    skipped_current: int
    failed: int
    stale_discarded: int
    deferred_recent_pending: int
    total_reported_tokens: int
    duration_seconds: float
    candidates: tuple[RepairCandidate, ...]


class RequestPacer:
    """Space initial provider-call starts within one sequential process."""

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval_seconds < 0:
            raise ReindexingConfigurationError(
                "minimum request interval must not be negative"
            )
        self._min_interval_seconds = min_interval_seconds
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_started_at: float | None = None

    def before_request(self) -> None:
        now = self._monotonic()
        if self._last_started_at is not None:
            remaining = (
                self._min_interval_seconds
                - (now - self._last_started_at)
            )
            if remaining > 0:
                self._sleep(remaining)
        self._last_started_at = self._monotonic()


def inspect_reindex_candidates(
    session: Session,
    *,
    owner_id: UUID,
    provider: EmbeddingProvider,
    entry_id: UUID | None = None,
    limit: int = DEFAULT_BATCH_LIMIT,
    pending_min_age_seconds: float = DEFAULT_PENDING_MIN_AGE_SECONDS,
    include_stale_pending: bool = True,
    now: datetime | None = None,
) -> RepairInspection:
    """Find owner-scoped entries that need embedding repair."""
    _validate_options(
        limit=limit,
        pending_min_age_seconds=pending_min_age_seconds,
    )
    inspected_at = now or datetime.now(UTC)
    if inspected_at.tzinfo is None or inspected_at.utcoffset() is None:
        raise ReindexingConfigurationError(
            "inspection timestamp must include a timezone"
        )
    pending_cutoff = inspected_at - timedelta(
        seconds=pending_min_age_seconds
    )

    statement = (
        select(
            Entry.id.label("entry_id"),
            Entry.owner_id,
            Entry.statement,
            Entry.index_status,
            Entry.updated_at,
            EntryEmbedding.entry_id.label("embedding_entry_id"),
            EntryEmbedding.content_hash,
            EntryEmbedding.provider.label("embedding_provider"),
            EntryEmbedding.model.label("embedding_model"),
        )
        .outerjoin(
            EntryEmbedding,
            EntryEmbedding.entry_id == Entry.id,
        )
        .where(Entry.owner_id == owner_id)
        .order_by(Entry.created_at.asc(), Entry.id.asc())
    )
    if entry_id is not None:
        statement = statement.where(Entry.id == entry_id)

    try:
        rows = session.execute(statement).mappings().all()
    except Exception:
        session.rollback()
        raise
    # Candidate inspection is read-only and must not leave a transaction open
    # while later provider requests are paced or retried.
    session.rollback()

    if entry_id is not None and not rows:
        raise ReindexingEntryNotFoundError

    candidates: list[RepairCandidate] = []
    seen_entry_ids: set[UUID] = set()
    eligible_entries = 0
    deferred_recent_pending = 0

    for row in rows:
        candidate = _candidate_from_row(
            row,
            provider=provider,
            pending_cutoff=pending_cutoff,
            include_stale_pending=include_stale_pending,
        )
        if candidate.entry_id in seen_entry_ids:
            continue
        seen_entry_ids.add(candidate.entry_id)

        if candidate.recent_pending:
            deferred_recent_pending += 1
            if entry_id is not None:
                candidates.append(candidate)
            continue

        if candidate.reasons:
            eligible_entries += 1
        # An explicit target is checked even when already current so the
        # indexing service can report a safe SKIPPED result. Collection runs
        # keep inspecting after the limit so their eligible count is accurate.
        if (
            (candidate.reasons or entry_id is not None)
            and (entry_id is not None or len(candidates) < limit)
        ):
            candidates.append(candidate)

    return RepairInspection(
        total_inspected=len(rows),
        eligible_entries=eligible_entries,
        candidates=tuple(candidates),
        deferred_recent_pending=deferred_recent_pending,
    )


def run_reindexing(
    session: Session,
    *,
    owner_id: UUID,
    provider: EmbeddingProvider,
    entry_id: UUID | None = None,
    limit: int = DEFAULT_BATCH_LIMIT,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    pending_min_age_seconds: float = DEFAULT_PENDING_MIN_AGE_SECONDS,
    include_stale_pending: bool = True,
    dry_run: bool = False,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> ReindexingReport:
    """Inspect and sequentially repair a bounded owner-scoped collection."""
    if min_interval_seconds < 0:
        raise ReindexingConfigurationError(
            "minimum request interval must not be negative"
        )
    started_at = monotonic()
    inspection = inspect_reindex_candidates(
        session,
        owner_id=owner_id,
        provider=provider,
        entry_id=entry_id,
        limit=limit,
        pending_min_age_seconds=pending_min_age_seconds,
        include_stale_pending=include_stale_pending,
        now=now,
    )
    if dry_run:
        return _report(
            dry_run=True,
            inspection=inspection,
            selected_entries=sum(
                not candidate.recent_pending
                for candidate in inspection.candidates
            ),
            duration_seconds=monotonic() - started_at,
        )

    pacer = RequestPacer(
        min_interval_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    indexed = skipped = failed = stale = tokens = selected = 0
    processed_ids: set[UUID] = set()

    for candidate in inspection.candidates:
        if candidate.recent_pending or candidate.entry_id in processed_ids:
            continue
        processed_ids.add(candidate.entry_id)
        selected += 1

        try:
            result = indexing_service.index_entry(
                session,
                owner_id=owner_id,
                entry_id=candidate.entry_id,
                provider=provider,
                before_provider_call=pacer.before_request,
            )
        except indexing_service.IndexingEntryNotFoundError:
            # The entry was deleted or changed ownership after inspection.
            stale += 1
            continue
        except SQLAlchemyError:
            session.rollback()
            raise

        tokens += result.total_tokens or 0
        if result.outcome is indexing_service.IndexingOutcome.INDEXED:
            indexed += 1
        elif result.outcome is indexing_service.IndexingOutcome.SKIPPED:
            skipped += 1
        elif result.outcome is indexing_service.IndexingOutcome.FAILED:
            failed += 1
        elif result.outcome is indexing_service.IndexingOutcome.STALE:
            stale += 1

    return _report(
        dry_run=False,
        inspection=inspection,
        selected_entries=selected,
        indexed_successfully=indexed,
        skipped_current=skipped,
        failed=failed,
        stale_discarded=stale,
        total_reported_tokens=tokens,
        duration_seconds=monotonic() - started_at,
    )


def _candidate_from_row(
    row: Mapping[str, object],
    *,
    provider: EmbeddingProvider,
    pending_cutoff: datetime,
    include_stale_pending: bool,
) -> RepairCandidate:
    entry_id = row["entry_id"]
    owner_id = row["owner_id"]
    statement = row["statement"]
    status = row["index_status"]
    updated_at = row["updated_at"]
    if not isinstance(entry_id, UUID) or not isinstance(owner_id, UUID):
        raise TypeError("repair inspection returned invalid entry identifiers")
    if not isinstance(statement, str) or not isinstance(status, str):
        raise TypeError("repair inspection returned invalid entry data")
    if not isinstance(updated_at, datetime):
        raise TypeError("repair inspection returned an invalid timestamp")

    if status == "pending" and (
        not include_stale_pending or updated_at > pending_cutoff
    ):
        return RepairCandidate(
            entry_id=entry_id,
            owner_id=owner_id,
            reasons=(),
            recent_pending=True,
        )

    reasons: list[RepairReason] = []
    if status == "failed":
        reasons.append(RepairReason.FAILED_STATUS)
    elif status == "pending":
        reasons.append(RepairReason.STALE_PENDING)

    if row["embedding_entry_id"] is None:
        reasons.append(RepairReason.MISSING_EMBEDDING)
    else:
        expected_hash = indexing_service.statement_content_hash(statement)
        if row["content_hash"] != expected_hash:
            reasons.append(RepairReason.CONTENT_HASH_MISMATCH)
        if row["embedding_provider"] != provider.name:
            reasons.append(RepairReason.PROVIDER_MISMATCH)
        if row["embedding_model"] != provider.model:
            reasons.append(RepairReason.MODEL_MISMATCH)

    return RepairCandidate(
        entry_id=entry_id,
        owner_id=owner_id,
        reasons=tuple(reasons),
    )


def _validate_options(*, limit: int, pending_min_age_seconds: float) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_BATCH_LIMIT:
        raise ReindexingConfigurationError(
            f"batch limit must be between 1 and {MAX_BATCH_LIMIT}"
        )
    if pending_min_age_seconds < 0:
        raise ReindexingConfigurationError(
            "pending minimum age must not be negative"
        )


def _report(
    *,
    dry_run: bool,
    inspection: RepairInspection,
    selected_entries: int,
    indexed_successfully: int = 0,
    skipped_current: int = 0,
    failed: int = 0,
    stale_discarded: int = 0,
    total_reported_tokens: int = 0,
    duration_seconds: float,
) -> ReindexingReport:
    return ReindexingReport(
        dry_run=dry_run,
        total_inspected=inspection.total_inspected,
        eligible_entries=inspection.eligible_entries,
        selected_entries=selected_entries,
        indexed_successfully=indexed_successfully,
        skipped_current=skipped_current,
        failed=failed,
        stale_discarded=stale_discarded,
        deferred_recent_pending=inspection.deferred_recent_pending,
        total_reported_tokens=total_reported_tokens,
        duration_seconds=round(max(duration_seconds, 0.0), 3),
        candidates=inspection.candidates,
    )
