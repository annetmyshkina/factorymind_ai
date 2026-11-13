"""add processed knowledge chunks and full-text search

Revision ID: a7d4e2c9b1f6
Revises: f4b7c9d2e1a6
Create Date: 2026-11-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "a7d4e2c9b1f6"
down_revision: str | Sequence[str] | None = "f4b7c9d2e1a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add processing state, deterministic chunks and PostgreSQL FTS index."""
    op.add_column(
        "knowledge_document_versions",
        sa.Column("processed_at", UTCDateTime(), nullable=True),
    )
    op.create_check_constraint(
        "ck_knowledge_document_versions_error_state",
        "knowledge_document_versions",
        "(status = 'failed' AND processing_error IS NOT NULL) "
        "OR (status <> 'failed' AND processing_error IS NULL)",
    )
    op.create_check_constraint(
        "ck_knowledge_document_versions_processed_state",
        "knowledge_document_versions",
        "status <> 'ready' OR processed_at IS NOT NULL",
    )

    op.create_table(
        "knowledge_document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "chunking_version",
            sa.String(length=30),
            server_default="paragraph-v1",
            nullable=False,
        ),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_document_chunks_index",
        ),
        sa.CheckConstraint(
            "length(content) > 0",
            name="ck_knowledge_document_chunks_content",
        ),
        sa.CheckConstraint(
            "length(checksum_sha256) = 64",
            name="ck_knowledge_document_chunks_checksum",
        ),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_knowledge_document_chunks_offsets",
        ),
        sa.CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) "
            "OR (page_start > 0 AND page_end >= page_start)",
            name="ck_knowledge_document_chunks_pages",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge_document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_knowledge_document_chunks_version_index",
        ),
    )
    op.create_index(
        "ix_knowledge_document_chunks_version",
        "knowledge_document_chunks",
        ["document_version_id", "chunk_index"],
        unique=False,
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_knowledge_document_chunks_search "
            "ON knowledge_document_chunks USING gin "
            "(to_tsvector('simple', content))",
        )


def downgrade() -> None:
    """Remove knowledge chunks and processing metadata."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX ix_knowledge_document_chunks_search")
    op.drop_index(
        "ix_knowledge_document_chunks_version",
        table_name="knowledge_document_chunks",
    )
    op.drop_table("knowledge_document_chunks")
    op.drop_constraint(
        "ck_knowledge_document_versions_processed_state",
        "knowledge_document_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_knowledge_document_versions_error_state",
        "knowledge_document_versions",
        type_="check",
    )
    op.drop_column("knowledge_document_versions", "processed_at")
