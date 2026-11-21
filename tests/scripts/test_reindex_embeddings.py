from uuid import UUID

import pytest

from app.services import reindexing_service
from scripts import reindex_embeddings


OWNER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
ENTRY_ID = UUID("223e4567-e89b-12d3-a456-426614174000")


def test_parser_uses_safe_pacing_and_batch_defaults() -> None:
    args = reindex_embeddings.build_parser().parse_args(
        ["--owner-id", str(OWNER_ID), "--dry-run"]
    )

    assert args.owner_id == OWNER_ID
    assert args.entry_id is None
    assert args.limit == 20
    assert args.interval_seconds == 30
    assert args.pending_min_age_seconds == 300
    assert args.dry_run is True


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--limit", "0"),
        ("--limit", "101"),
        ("--interval-seconds", "-1"),
        ("--pending-min-age-seconds", "-1"),
    ],
)
def test_parser_rejects_unsafe_limits(option: str, value: str) -> None:
    with pytest.raises(SystemExit):
        reindex_embeddings.build_parser().parse_args(
            ["--owner-id", str(OWNER_ID), option, value]
        )


def test_dry_run_report_shows_ids_and_reasons_without_content(capsys) -> None:
    candidate = reindexing_service.RepairCandidate(
        entry_id=ENTRY_ID,
        owner_id=OWNER_ID,
        reasons=(reindexing_service.RepairReason.MISSING_EMBEDDING,),
    )
    report = reindexing_service.ReindexingReport(
        dry_run=True,
        total_inspected=1,
        eligible_entries=1,
        selected_entries=1,
        indexed_successfully=0,
        skipped_current=0,
        failed=0,
        stale_discarded=0,
        deferred_recent_pending=0,
        total_reported_tokens=0,
        duration_seconds=0.125,
        candidates=(candidate,),
    )

    reindex_embeddings.print_report(report)

    output = capsys.readouterr().out
    assert str(ENTRY_ID) in output
    assert "missing_embedding" in output
    assert "Total entries inspected: 1" in output
    assert "no provider calls or data changes" in output
