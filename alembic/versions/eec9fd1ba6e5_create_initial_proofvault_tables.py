"""Create initial ProofVault tables.

Revision ID: eec9fd1ba6e5
Revises:
Create Date: 2026-11-09 01:50:35.403227
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR


# Revision identifiers, used by Alembic.
revision: str = "eec9fd1ba6e5"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the application tables and enable vector storage."""
    op.execute("CREATE SCHEMA IF NOT EXISTS extensions")
    op.execute(
        "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions"
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_courses_name_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["auth.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "owner_id",
            name="uq_courses_id_owner",
        ),
        schema="proofvault",
    )

    op.create_index(
        "ix_courses_owner_id",
        "courses",
        ["owner_id"],
        unique=False,
        schema="proofvault",
    )

    op.create_table(
        "entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("proof", sa.Text(), nullable=True),
        sa.Column("topic", sa.String(length=100), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column(
            "index_status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "index_status IN ('pending', 'ready', 'failed')",
            name="ck_entries_index_status",
        ),
        sa.CheckConstraint(
            "kind IN ('theorem', 'problem')",
            name="ck_entries_kind",
        ),
        sa.CheckConstraint(
            "length(trim(statement)) > 0",
            name="ck_entries_statement_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_entries_title_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["course_id", "owner_id"],
            [
                "proofvault.courses.id",
                "proofvault.courses.owner_id",
            ],
            name="fk_entries_course_owner",
            ondelete="SET NULL (course_id)",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["auth.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="proofvault",
    )

    op.create_index(
        "ix_entries_owner_course",
        "entries",
        ["owner_id", "course_id"],
        unique=False,
        schema="proofvault",
    )

    op.create_index(
        "ix_entries_owner_created_id",
        "entries",
        ["owner_id", "created_at", "id"],
        unique=False,
        schema="proofvault",
    )

    op.create_table(
        "entry_embeddings",
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", VECTOR(1024), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_entry_embeddings_content_hash",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["proofvault.entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entry_id"),
        schema="proofvault",
    )


def downgrade() -> None:
    """Remove application tables, preserving schemas and extensions."""
    op.drop_table(
        "entry_embeddings",
        schema="proofvault",
    )

    op.drop_index(
        "ix_entries_owner_created_id",
        table_name="entries",
        schema="proofvault",
    )

    op.drop_index(
        "ix_entries_owner_course",
        table_name="entries",
        schema="proofvault",
    )

    op.drop_table(
        "entries",
        schema="proofvault",
    )

    op.drop_index(
        "ix_courses_owner_id",
        table_name="courses",
        schema="proofvault",
    )

    op.drop_table(
        "courses",
        schema="proofvault",
    )