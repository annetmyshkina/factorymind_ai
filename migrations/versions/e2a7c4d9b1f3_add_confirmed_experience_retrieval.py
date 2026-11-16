"""add confirmed experience retrieval and analysis snapshots

Revision ID: e2a7c4d9b1f3
Revises: c9f6a4e2d3b8
Create Date: 2026-11-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a7c4d9b1f3"
down_revision: str | Sequence[str] | None = "c9f6a4e2d3b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index active resolutions and persist exact experience used by analyses."""
    op.add_column(
        "incident_resolutions",
        sa.Column("search_text", sa.Text(), nullable=True),
    )
    separator = "chr(10)" if op.get_bind().dialect.name == "postgresql" else "char(10)"
    op.execute(
        "UPDATE incident_resolutions SET search_text = "
        f"COALESCE(CAST(checks_performed AS TEXT), '') || {separator} || "
        f"COALESCE(confirmed_cause, '') || {separator} || "
        f"COALESCE(CAST(actions_taken AS TEXT), '') || {separator} || outcome",
    )
    op.alter_column("incident_resolutions", "search_text", nullable=False)

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_incident_resolutions_search "
            "ON incident_resolutions USING gin "
            "(to_tsvector('simple', search_text))",
        )

    op.create_table(
        "incident_analysis_experiences",
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("resolution_id", sa.Integer(), nullable=False),
        sa.Column("resolution_revision", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "rank > 0",
            name="ck_incident_analysis_experiences_rank",
        ),
        sa.CheckConstraint(
            "score >= 0",
            name="ck_incident_analysis_experiences_score",
        ),
        sa.CheckConstraint(
            "resolution_revision > 0",
            name="ck_incident_analysis_experiences_revision",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["incident_analyses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolution_id"],
            ["incident_resolutions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("analysis_id", "resolution_id"),
        sa.UniqueConstraint(
            "analysis_id",
            "rank",
            name="uq_incident_analysis_experiences_analysis_rank",
        ),
    )


def downgrade() -> None:
    """Remove confirmed experience snapshots and search index."""
    op.drop_table("incident_analysis_experiences")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX ix_incident_resolutions_search")
    op.drop_column("incident_resolutions", "search_text")
