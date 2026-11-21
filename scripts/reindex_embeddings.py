"""Inspect and repair owner-scoped ProofVault statement embeddings."""

import argparse
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies.embedding import get_embedding_provider
from app.services.reindexing_service import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_MIN_INTERVAL_SECONDS,
    DEFAULT_PENDING_MIN_AGE_SECONDS,
    MAX_BATCH_LIMIT,
    ReindexingEntryNotFoundError,
    ReindexingReport,
    run_reindexing,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect and repair statement embeddings for one ProofVault owner."
        )
    )
    parser.add_argument("--owner-id", type=UUID, required=True)
    parser.add_argument("--entry-id", type=UUID)
    parser.add_argument(
        "--limit",
        type=_batch_limit,
        default=DEFAULT_BATCH_LIMIT,
        help=(
            f"maximum entries selected per run (default: "
            f"{DEFAULT_BATCH_LIMIT}, maximum: {MAX_BATCH_LIMIT})"
        ),
    )
    parser.add_argument(
        "--interval-seconds",
        type=_nonnegative_float,
        default=DEFAULT_MIN_INTERVAL_SECONDS,
        help="minimum time between provider request starts (default: 30)",
    )
    parser.add_argument(
        "--pending-min-age-seconds",
        type=_nonnegative_float,
        default=DEFAULT_PENDING_MIN_AGE_SECONDS,
        help="minimum age before pending work is considered stale (default: 300)",
    )
    parser.add_argument(
        "--skip-stale-pending",
        action="store_true",
        help="do not select pending entries, regardless of age",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="inspect and report without calling Voyage or changing data",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Importing the session module loads deployment configuration, so keep it
    # out of module import paths used by focused unit tests.
    from app.db.session import SessionLocal, engine

    provider = get_embedding_provider()
    try:
        with SessionLocal() as session:
            report = run_reindexing(
                session,
                owner_id=args.owner_id,
                entry_id=args.entry_id,
                provider=provider,
                limit=args.limit,
                min_interval_seconds=args.interval_seconds,
                pending_min_age_seconds=args.pending_min_age_seconds,
                include_stale_pending=not args.skip_stale_pending,
                dry_run=args.dry_run,
            )
    except ReindexingEntryNotFoundError:
        print("Target entry was not found for the supplied owner.")
        return 2
    except SQLAlchemyError as error:
        print(f"Reindexing stopped after a database error: {type(error).__name__}")
        return 1
    finally:
        engine.dispose()

    print_report(report)
    return 1 if report.failed else 0


def print_report(report: ReindexingReport) -> None:
    if report.dry_run:
        print("Embedding repair dry run (no provider calls or data changes)")
        for candidate in report.candidates:
            if candidate.recent_pending:
                description = "recent pending; deferred"
            elif candidate.reasons:
                description = ", ".join(reason.value for reason in candidate.reasons)
            else:
                description = "already current"
            print(f"- {candidate.entry_id}: {description}")
    else:
        print("Embedding repair run complete")

    print(f"Total entries inspected: {report.total_inspected}")
    print(f"Eligible entries: {report.eligible_entries}")
    print(f"Entries selected: {report.selected_entries}")
    print(f"Indexed successfully: {report.indexed_successfully}")
    print(f"Skipped because already current: {report.skipped_current}")
    print(f"Failed: {report.failed}")
    print(f"Stale results discarded: {report.stale_discarded}")
    print(f"Recent pending entries deferred: {report.deferred_recent_pending}")
    print(f"Total reported tokens consumed: {report.total_reported_tokens}")
    print(f"Execution duration: {report.duration_seconds:.3f} seconds")


def _batch_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("limit must be an integer") from None
    if not 1 <= parsed <= MAX_BATCH_LIMIT:
        raise argparse.ArgumentTypeError(
            f"limit must be between 1 and {MAX_BATCH_LIMIT}"
        )
    return parsed


def _nonnegative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("value must be numeric") from None
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
