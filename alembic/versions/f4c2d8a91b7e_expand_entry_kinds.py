"""Expand entry kinds for the mathematical library.

Revision ID: f4c2d8a91b7e
Revises: eec9fd1ba6e5
Create Date: 2026-11-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f4c2d8a91b7e"
down_revision: Union[str, Sequence[str], None] = "eec9fd1ba6e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EXPANDED_ENTRY_KIND_CONSTRAINT = (
    "kind IN ("
    "'theorem', 'proposition', 'lemma', 'corollary', "
    "'definition', 'problem', 'conjecture', 'identity', 'other'"
    ")"
)
LEGACY_ENTRY_KIND_CONSTRAINT = "kind IN ('theorem', 'problem')"


def upgrade() -> None:
    """Allow the expanded V1 organizational entry categories."""
    op.drop_constraint(
        "ck_entries_kind",
        "entries",
        schema="proofvault",
        type_="check",
    )
    op.create_check_constraint(
        "ck_entries_kind",
        "entries",
        EXPANDED_ENTRY_KIND_CONSTRAINT,
        schema="proofvault",
    )


def downgrade() -> None:
    """Restore the original two-kind constraint without rewriting data."""
    op.drop_constraint(
        "ck_entries_kind",
        "entries",
        schema="proofvault",
        type_="check",
    )
    # Deliberately do not coerce newer kinds into another value. PostgreSQL
    # will refuse this downgrade if incompatible rows exist, avoiding data loss.
    op.create_check_constraint(
        "ck_entries_kind",
        "entries",
        LEGACY_ENTRY_KIND_CONSTRAINT,
        schema="proofvault",
    )
