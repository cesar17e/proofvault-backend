import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingBatch,
    EmbeddingProviderError,
)
from app.services import indexing_service, reindexing_service


OWNER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
ENTRY_IDS = tuple(
    UUID(f"{number}23e4567-e89b-12d3-a456-426614174000")
    for number in range(2, 9)
)
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
STATEMENT = "If $a_n \\to L$, then $(a_n)$ is bounded."


class FakeProvider:
    name = "voyage"
    model = "voyage-4"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, *, error=None, before_call=None) -> None:
        self.error = error
        self.before_call = before_call
        self.documents: list[list[str]] = []

    def embed_documents(self, texts) -> EmbeddingBatch:
        if self.before_call is not None:
            self.before_call()
        self.documents.append(list(texts))
        if self.error is not None:
            raise self.error
        return EmbeddingBatch(
            embeddings=(tuple([0.25] * EMBEDDING_DIMENSIONS),),
            total_tokens=11,
        )


def row(
    entry_id: UUID,
    *,
    status: str = "ready",
    statement: str = STATEMENT,
    updated_at: datetime = NOW,
    embedding: bool = True,
    content_hash: str | None = None,
    provider: str = "voyage",
    model: str = "voyage-4",
) -> dict:
    return {
        "entry_id": entry_id,
        "owner_id": OWNER_ID,
        "statement": statement,
        "index_status": status,
        "updated_at": updated_at,
        "embedding_entry_id": entry_id if embedding else None,
        "content_hash": (
            content_hash
            if content_hash is not None
            else hashlib.sha256(statement.encode("utf-8")).hexdigest()
        ),
        "embedding_provider": provider,
        "embedding_model": model,
    }


def inspection_session(rows: list[dict]) -> MagicMock:
    session = MagicMock(spec=Session)
    session.execute.return_value.mappings.return_value.all.return_value = rows
    return session


def indexing_session(entry, embedding=None) -> MagicMock:
    session = MagicMock(spec=Session)
    initial_result = MagicMock()
    initial_result.one_or_none.return_value = (entry, embedding)
    session.execute.return_value = initial_result
    session.scalar.return_value = entry
    return session


def candidate(
    entry_id: UUID = ENTRY_IDS[0],
    *reasons: reindexing_service.RepairReason,
) -> reindexing_service.RepairCandidate:
    return reindexing_service.RepairCandidate(
        entry_id=entry_id,
        owner_id=OWNER_ID,
        reasons=reasons
        or (reindexing_service.RepairReason.MISSING_EMBEDDING,),
    )


def patch_inspection(monkeypatch, *candidates) -> None:
    monkeypatch.setattr(
        reindexing_service,
        "inspect_reindex_candidates",
        lambda *args, **kwargs: reindexing_service.RepairInspection(
            total_inspected=len(candidates),
            eligible_entries=sum(bool(item.reasons) for item in candidates),
            candidates=tuple(candidates),
            deferred_recent_pending=0,
        ),
    )


def test_inspection_finds_all_repair_conditions_and_defers_recent_pending() -> None:
    stale_time = NOW - timedelta(minutes=10)
    changed_statement = "Every convergent real sequence is bounded."
    rows = [
        row(ENTRY_IDS[0], status="failed"),
        row(
            ENTRY_IDS[1],
            status="pending",
            updated_at=stale_time,
            embedding=False,
        ),
        row(ENTRY_IDS[2], status="pending", embedding=False),
        row(ENTRY_IDS[3], embedding=False),
        row(
            ENTRY_IDS[4],
            statement=changed_statement,
            content_hash="0" * 64,
        ),
        row(
            ENTRY_IDS[5],
            provider="old-provider",
            model="old-model",
        ),
        row(ENTRY_IDS[6]),
    ]
    session = inspection_session(rows)

    inspection = reindexing_service.inspect_reindex_candidates(
        session,
        owner_id=OWNER_ID,
        provider=FakeProvider(),
        now=NOW,
    )

    assert inspection.total_inspected == 7
    assert inspection.eligible_entries == 5
    assert inspection.deferred_recent_pending == 1
    assert [item.entry_id for item in inspection.candidates] == [
        ENTRY_IDS[0],
        ENTRY_IDS[1],
        ENTRY_IDS[3],
        ENTRY_IDS[4],
        ENTRY_IDS[5],
    ]
    reasons = {item.entry_id: set(item.reasons) for item in inspection.candidates}
    assert reasons[ENTRY_IDS[0]] == {
        reindexing_service.RepairReason.FAILED_STATUS
    }
    assert reasons[ENTRY_IDS[1]] == {
        reindexing_service.RepairReason.STALE_PENDING,
        reindexing_service.RepairReason.MISSING_EMBEDDING,
    }
    assert reasons[ENTRY_IDS[3]] == {
        reindexing_service.RepairReason.MISSING_EMBEDDING
    }
    assert reasons[ENTRY_IDS[4]] == {
        reindexing_service.RepairReason.CONTENT_HASH_MISMATCH
    }
    assert reasons[ENTRY_IDS[5]] == {
        reindexing_service.RepairReason.PROVIDER_MISMATCH,
        reindexing_service.RepairReason.MODEL_MISMATCH,
    }
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()


def test_target_lookup_is_owner_scoped_and_missing_target_is_rejected() -> None:
    session = inspection_session([])

    with pytest.raises(reindexing_service.ReindexingEntryNotFoundError):
        reindexing_service.inspect_reindex_candidates(
            session,
            owner_id=OWNER_ID,
            entry_id=ENTRY_IDS[0],
            provider=FakeProvider(),
            now=NOW,
        )

    statement = session.execute.call_args.args[0]
    sql = str(statement)
    params = statement.compile().params.values()
    assert "proofvault.entries.owner_id" in sql
    assert "proofvault.entries.id" in sql
    assert OWNER_ID in params
    assert ENTRY_IDS[0] in params
    session.rollback.assert_called_once_with()


def test_collection_limit_bounds_selection_but_counts_all_eligible() -> None:
    session = inspection_session(
        [row(entry_id, embedding=False) for entry_id in ENTRY_IDS[:3]]
    )

    inspection = reindexing_service.inspect_reindex_candidates(
        session,
        owner_id=OWNER_ID,
        provider=FakeProvider(),
        limit=2,
        now=NOW,
    )

    assert inspection.total_inspected == 3
    assert inspection.eligible_entries == 3
    assert [item.entry_id for item in inspection.candidates] == list(
        ENTRY_IDS[:2]
    )


def test_recent_targeted_pending_entry_is_deferred(monkeypatch) -> None:
    session = inspection_session(
        [row(ENTRY_IDS[0], status="pending", embedding=False)]
    )
    index_entry = MagicMock()
    monkeypatch.setattr(indexing_service, "index_entry", index_entry)

    report = reindexing_service.run_reindexing(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_IDS[0],
        provider=FakeProvider(),
        min_interval_seconds=0,
        now=NOW,
    )

    assert report.deferred_recent_pending == 1
    assert report.selected_entries == 0
    assert report.indexed_successfully == 0
    index_entry.assert_not_called()


def test_successful_repair_uses_existing_indexing_service(monkeypatch) -> None:
    entry = SimpleNamespace(
        id=ENTRY_IDS[0],
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="failed",
        updated_at=NOW,
    )
    session = indexing_session(entry)
    provider = FakeProvider()
    patch_inspection(monkeypatch, candidate())

    report = reindexing_service.run_reindexing(
        session,
        owner_id=OWNER_ID,
        provider=provider,
        min_interval_seconds=0,
    )

    assert provider.documents == [[STATEMENT]]
    assert report.indexed_successfully == 1
    assert report.total_reported_tokens == 11
    assert report.failed == 0
    assert entry.index_status == "ready"


def test_current_embedding_is_skipped_and_failed_status_is_repaired(
    monkeypatch,
) -> None:
    content_hash = indexing_service.statement_content_hash(STATEMENT)
    entry = SimpleNamespace(
        id=ENTRY_IDS[0],
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="failed",
        updated_at=NOW,
    )
    embedding = SimpleNamespace(
        entry_id=ENTRY_IDS[0],
        content_hash=content_hash,
        provider="voyage",
        model="voyage-4",
    )
    session = indexing_session(entry, embedding)
    provider = FakeProvider()
    patch_inspection(
        monkeypatch,
        candidate(ENTRY_IDS[0], reindexing_service.RepairReason.FAILED_STATUS),
    )

    report = reindexing_service.run_reindexing(
        session,
        owner_id=OWNER_ID,
        provider=provider,
        min_interval_seconds=0,
    )

    assert report.skipped_current == 1
    assert report.indexed_successfully == 0
    assert provider.documents == []
    assert entry.index_status == "ready"


def test_provider_failure_preserves_statement_and_run_continues_reporting(
    monkeypatch,
) -> None:
    entry = SimpleNamespace(
        id=ENTRY_IDS[0],
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="failed",
        updated_at=NOW,
    )
    session = indexing_session(entry)
    provider = FakeProvider(
        error=EmbeddingProviderError(
            "safe provider failure",
            error_type="RateLimitError",
        )
    )
    patch_inspection(monkeypatch, candidate())

    report = reindexing_service.run_reindexing(
        session,
        owner_id=OWNER_ID,
        provider=provider,
        min_interval_seconds=0,
    )

    assert report.failed == 1
    assert report.indexed_successfully == 0
    assert report.total_reported_tokens == 0
    assert entry.statement == STATEMENT
    assert entry.index_status == "failed"


def test_changed_statement_discards_old_provider_result(monkeypatch) -> None:
    entry = SimpleNamespace(
        id=ENTRY_IDS[0],
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="failed",
        updated_at=NOW,
    )
    session = indexing_session(entry)

    def replace_statement() -> None:
        entry.statement = "A newer statement from another request."
        entry.index_status = "pending"

    provider = FakeProvider(before_call=replace_statement)
    patch_inspection(monkeypatch, candidate())

    report = reindexing_service.run_reindexing(
        session,
        owner_id=OWNER_ID,
        provider=provider,
        min_interval_seconds=0,
    )

    assert report.stale_discarded == 1
    assert report.total_reported_tokens == 11
    assert entry.index_status == "pending"
    assert session.execute.call_count == 1


def test_dry_run_does_not_call_provider_or_modify_database() -> None:
    session = inspection_session(
        [row(ENTRY_IDS[0], status="failed", embedding=False)]
    )
    provider = FakeProvider()

    report = reindexing_service.run_reindexing(
        session,
        owner_id=OWNER_ID,
        provider=provider,
        dry_run=True,
        now=NOW,
    )

    assert report.dry_run is True
    assert report.total_inspected == 1
    assert report.eligible_entries == 1
    assert report.selected_entries == 1
    assert provider.documents == []
    session.commit.assert_not_called()
    session.add.assert_not_called()


def test_pacing_spaces_only_actual_provider_request_starts(monkeypatch) -> None:
    candidates = tuple(candidate(entry_id) for entry_id in ENTRY_IDS[:3])
    patch_inspection(monkeypatch, *candidates)
    clock = [0.0]
    request_starts: list[float] = []
    sleeps: list[float] = []

    def monotonic() -> float:
        return clock[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    def fake_index(*args, entry_id, before_provider_call, **kwargs):
        before_provider_call()
        request_starts.append(clock[0])
        clock[0] += 5
        return indexing_service.IndexingResult(
            entry_id=entry_id,
            outcome=indexing_service.IndexingOutcome.INDEXED,
            index_status="ready",
            content_hash="a" * 64,
            provider="voyage",
            model="voyage-4",
            duration_ms=5_000,
            total_tokens=10,
        )

    monkeypatch.setattr(indexing_service, "index_entry", fake_index)

    report = reindexing_service.run_reindexing(
        MagicMock(spec=Session),
        owner_id=OWNER_ID,
        provider=FakeProvider(),
        min_interval_seconds=30,
        monotonic=monotonic,
        sleep=sleep,
    )

    assert request_starts == [0.0, 30.0, 60.0]
    assert sleeps == [25.0, 25.0]
    assert report.indexed_successfully == 3
    assert report.total_reported_tokens == 30
    assert report.duration_seconds == 65.0


def test_duplicate_candidates_are_processed_once(monkeypatch) -> None:
    duplicate = candidate()
    patch_inspection(monkeypatch, duplicate, duplicate)
    index_entry = MagicMock(
        return_value=indexing_service.IndexingResult(
            entry_id=duplicate.entry_id,
            outcome=indexing_service.IndexingOutcome.SKIPPED,
            index_status="ready",
            content_hash="a" * 64,
            provider="voyage",
            model="voyage-4",
            duration_ms=0,
        )
    )
    monkeypatch.setattr(indexing_service, "index_entry", index_entry)

    report = reindexing_service.run_reindexing(
        MagicMock(spec=Session),
        owner_id=OWNER_ID,
        provider=FakeProvider(),
        min_interval_seconds=0,
    )

    assert report.selected_entries == 1
    assert report.skipped_current == 1
    index_entry.assert_called_once()


def test_inspection_database_error_rolls_back() -> None:
    session = MagicMock(spec=Session)
    session.execute.side_effect = SQLAlchemyError("database unavailable")

    with pytest.raises(SQLAlchemyError):
        reindexing_service.inspect_reindex_candidates(
            session,
            owner_id=OWNER_ID,
            provider=FakeProvider(),
            now=NOW,
        )

    session.rollback.assert_called_once_with()
