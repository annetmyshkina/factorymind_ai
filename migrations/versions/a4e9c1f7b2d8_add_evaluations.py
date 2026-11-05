"""add evaluations

Revision ID: a4e9c1f7b2d8
Revises: 782f6caa999f
Create Date: 2026-11-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "a4e9c1f7b2d8"
down_revision: str | Sequence[str] | None = "782f6caa999f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("llm_call_id", sa.Integer(), nullable=False),
        sa.Column("evaluator", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["llm_call_id"],
            ["llm_calls.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "llm_call_id",
            name="uq_evaluations_llm_call_id",
        ),
    )
    op.create_index(
        op.f("ix_evaluations_llm_call_id"),
        "evaluations",
        ["llm_call_id"],
        unique=False,
    )

    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("criterion", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "score >= 0 AND score <= 2",
            name="ck_evaluation_results_score",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["evaluations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id",
            "criterion",
            name="uq_evaluation_results_evaluation_criterion",
        ),
    )
    op.create_index(
        op.f("ix_evaluation_results_evaluation_id"),
        "evaluation_results",
        ["evaluation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_evaluation_results_evaluation_id"),
        table_name="evaluation_results",
    )
    op.drop_table("evaluation_results")
    op.drop_index(
        op.f("ix_evaluations_llm_call_id"),
        table_name="evaluations",
    )
    op.drop_table("evaluations")
