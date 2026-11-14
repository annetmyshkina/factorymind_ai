"""add persisted incident analyses and source links

Revision ID: b8e5f3d1c2a7
Revises: a7d4e2c9b1f6
Create Date: 2026-11-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "b8e5f3d1c2a7"
down_revision: str | Sequence[str] | None = "a7d4e2c9b1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable incident analyses and their exact retrieval context."""
    op.create_table(
        "incident_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("llm_call_id", sa.Integer(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'insufficient')",
            name="ck_incident_analyses_status",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND llm_call_id IS NOT NULL) "
            "OR (status = 'insufficient' AND llm_call_id IS NULL)",
            name="ck_incident_analyses_call_state",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["llm_call_id"],
            ["llm_calls.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("llm_call_id"),
    )
    op.create_index(
        "ix_incident_analyses_incident_created",
        "incident_analyses",
        ["incident_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "incident_analysis_sources",
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "rank > 0",
            name="ck_incident_analysis_sources_rank",
        ),
        sa.CheckConstraint(
            "score >= 0",
            name="ck_incident_analysis_sources_score",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["incident_analyses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["knowledge_document_chunks.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("analysis_id", "chunk_id"),
        sa.UniqueConstraint(
            "analysis_id",
            "rank",
            name="uq_incident_analysis_sources_analysis_rank",
        ),
    )


def downgrade() -> None:
    """Drop incident analysis history and source links."""
    op.drop_table("incident_analysis_sources")
    op.drop_index(
        "ix_incident_analyses_incident_created",
        table_name="incident_analyses",
    )
    op.drop_table("incident_analyses")
