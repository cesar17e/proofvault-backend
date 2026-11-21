import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingBatch,
    EmbeddingProviderError,
)
from app.services import indexing_service


OWNER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
OTHER_OWNER_ID = UUID("223e4567-e89b-12d3-a456-426614174000")
ENTRY_ID = UUID("323e4567-e89b-12d3-a456-426614174000")
STATEMENT = "  If $a_n \\to L$, then $(a_n)$ is bounded.  "


class StubProvider:
    name = "voyage"
    model = "voyage-4"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(
        self,
        *,
        error: EmbeddingProviderError | None = None,
        before_call=None,
    ) -> None:
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
            total_tokens=17,
        )


def make_session(
    entry,
    embedding=None,
) -> MagicMock:
    session = MagicMock(spec=Session)
    initial_result = MagicMock()
    initial_result.one_or_none.return_value = (entry, embedding)
    session.execute.return_value = initial_result
    session.scalar.return_value = entry
    return session


def test_statement_hash_uses_exact_utf8_source() -> None:
    expected = hashlib.sha256(STATEMENT.encode("utf-8")).hexdigest()

    assert indexing_service.statement_content_hash(STATEMENT) == expected
    assert indexing_service.statement_content_hash(STATEMENT.strip()) != expected
    assert len(expected) == 64


def test_successful_indexing_ends_read_transaction_before_provider_call() -> None:
    entry = SimpleNamespace(
        id=ENTRY_ID,
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="pending",
    )
    session = make_session(entry)
    provider = StubProvider(
        before_call=lambda: session.commit.assert_called_once_with()
    )
    before_provider_call = MagicMock(
        side_effect=lambda: session.commit.assert_called_once_with()
    )

    result = indexing_service.index_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        provider=provider,
        before_provider_call=before_provider_call,
    )

    assert provider.documents == [[STATEMENT]]
    assert result.outcome is indexing_service.IndexingOutcome.INDEXED
    assert result.index_status.value == "ready"
    assert result.total_tokens == 17
    assert entry.index_status == "ready"
    assert session.commit.call_count == 2
    before_provider_call.assert_called_once_with()

    preparation_statement = session.execute.call_args_list[0].args[0]
    preparation_sql = str(
        preparation_statement.compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE OF entries" in preparation_sql

    upsert = session.execute.call_args_list[-1].args[0]
    sql = str(upsert.compile(dialect=postgresql.dialect()))
    params = upsert.compile(dialect=postgresql.dialect()).params
    assert "INSERT INTO proofvault.entry_embeddings" in sql
    assert "ON CONFLICT (entry_id) DO UPDATE" in sql
    assert params["provider"] == "voyage"
    assert params["model"] == "voyage-4"
    assert params["content_hash"] == result.content_hash
    assert len(params["embedding"]) == EMBEDDING_DIMENSIONS


def test_matching_embedding_is_skipped_and_repairs_status() -> None:
    content_hash = indexing_service.statement_content_hash(STATEMENT)
    entry = SimpleNamespace(
        id=ENTRY_ID,
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="failed",
    )
    embedding = SimpleNamespace(
        entry_id=ENTRY_ID,
        provider="voyage",
        model="voyage-4",
        content_hash=content_hash,
    )
    session = make_session(entry, embedding)
    provider = StubProvider()
    before_provider_call = MagicMock()

    result = indexing_service.index_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        provider=provider,
        before_provider_call=before_provider_call,
    )

    assert result.outcome is indexing_service.IndexingOutcome.SKIPPED
    assert entry.index_status == "ready"
    assert provider.documents == []
    before_provider_call.assert_not_called()
    session.commit.assert_called_once_with()


def test_obsolete_embedding_is_deleted_before_reindexing() -> None:
    entry = SimpleNamespace(
        id=ENTRY_ID,
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="ready",
    )
    embedding = SimpleNamespace(
        entry_id=ENTRY_ID,
        provider="voyage",
        model="old-model",
        content_hash=indexing_service.statement_content_hash(STATEMENT),
    )
    session = make_session(entry, embedding)
    provider = StubProvider()

    indexing_service.index_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        provider=provider,
    )

    delete_statement = session.execute.call_args_list[1].args[0]
    delete_sql = str(delete_statement.compile(dialect=postgresql.dialect()))
    assert "DELETE FROM proofvault.entry_embeddings" in delete_sql
    assert session.commit.call_count == 2


def test_provider_failure_preserves_entry_and_marks_it_failed() -> None:
    entry = SimpleNamespace(
        id=ENTRY_ID,
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="pending",
    )
    session = make_session(entry)
    provider = StubProvider(
        error=EmbeddingProviderError(
            "safe provider failure",
            error_type="Timeout",
        )
    )

    result = indexing_service.index_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        provider=provider,
    )

    assert result.outcome is indexing_service.IndexingOutcome.FAILED
    assert result.failure_type == "Timeout"
    assert entry.statement == STATEMENT
    assert entry.index_status == "failed"
    assert session.commit.call_count == 2
    session.rollback.assert_not_called()


@pytest.mark.parametrize("provider_fails", [False, True])
def test_stale_provider_result_cannot_overwrite_newer_statement(
    provider_fails: bool,
) -> None:
    entry = SimpleNamespace(
        id=ENTRY_ID,
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="pending",
    )
    session = make_session(entry)

    def replace_statement_while_provider_runs() -> None:
        entry.statement = "A newer statement submitted by another request."
        entry.index_status = "pending"

    error = None
    if provider_fails:
        error = EmbeddingProviderError(
            "old request failed",
            error_type="Timeout",
        )
    provider = StubProvider(
        error=error,
        before_call=replace_statement_while_provider_runs,
    )

    result = indexing_service.index_entry(
        session,
        owner_id=OWNER_ID,
        entry_id=ENTRY_ID,
        provider=provider,
    )

    assert result.outcome is indexing_service.IndexingOutcome.STALE
    assert result.index_status.value == "pending"
    assert entry.index_status == "pending"
    assert session.execute.call_count == 1
    assert session.commit.call_count == 2

    locking_statement = session.scalar.call_args.args[0]
    assert locking_statement.get_execution_options()["populate_existing"] is True
    sql = str(locking_statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql


def test_missing_or_foreign_entry_stops_before_provider_call() -> None:
    session = MagicMock(spec=Session)
    initial_result = MagicMock()
    initial_result.one_or_none.return_value = None
    session.execute.return_value = initial_result
    provider = StubProvider()

    with pytest.raises(indexing_service.IndexingEntryNotFoundError):
        indexing_service.index_entry(
            session,
            owner_id=OTHER_OWNER_ID,
            entry_id=ENTRY_ID,
            provider=provider,
        )

    assert provider.documents == []
    statement = session.execute.call_args.args[0]
    sql = str(statement)
    params = statement.compile().params.values()
    assert "proofvault.entries.id" in sql
    assert "proofvault.entries.owner_id" in sql
    assert ENTRY_ID in params
    assert OTHER_OWNER_ID in params
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()


def test_persistence_failure_rolls_back_ready_transition() -> None:
    entry = SimpleNamespace(
        id=ENTRY_ID,
        owner_id=OWNER_ID,
        statement=STATEMENT,
        index_status="pending",
    )
    session = make_session(entry)
    session.commit.side_effect = [None, RuntimeError("database unavailable")]

    with pytest.raises(RuntimeError, match="database unavailable"):
        indexing_service.index_entry(
            session,
            owner_id=OWNER_ID,
            entry_id=ENTRY_ID,
            provider=StubProvider(),
        )

    session.rollback.assert_called_once_with()


def test_provider_dimension_must_match_database_schema() -> None:
    provider = StubProvider()
    provider.dimensions = 512
    session = MagicMock(spec=Session)

    with pytest.raises(indexing_service.IndexingConfigurationError):
        indexing_service.index_entry(
            session,
            owner_id=OWNER_ID,
            entry_id=ENTRY_ID,
            provider=provider,
        )

    session.execute.assert_not_called()
