"""add experiments and experiment_runs

Revision ID: 782f6caa999f
Revises: d5a1c7e9f2b4
Create Date: 2026-11-04 11:57:29.598437

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "782f6caa999f"
down_revision: str | Sequence[str] | None = "d5a1c7e9f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt_version_id", sa.Integer(), nullable=False),
        sa.Column("scenario", sa.JSON(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiments_created_at",
        "experiments",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experiments_prompt_version_id"),
        "experiments",
        ["prompt_version_id"],
        unique=False,
    )

    op.create_table(
        "experiment_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", UTCDateTime(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_experiment_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id",
            "provider",
            "model",
            name="uq_experiment_runs_exp_provider_model",
        ),
    )
    op.create_index(
        op.f("ix_experiment_runs_experiment_id"),
        "experiment_runs",
        ["experiment_id"],
        unique=False,
    )
    op.create_index(
        "ix_experiment_runs_status",
        "experiment_runs",
        ["status"],
        unique=False,
    )

    op.add_column(
        "llm_calls",
        sa.Column("experiment_run_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_llm_calls_experiment_run_id"),
        "llm_calls",
        ["experiment_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_llm_calls_experiment_run_id",
        "llm_calls",
        "experiment_runs",
        ["experiment_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_llm_calls_experiment_run_id",
        "llm_calls",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_llm_calls_experiment_run_id"),
        table_name="llm_calls",
    )
    op.drop_column("llm_calls", "experiment_run_id")
    op.drop_index("ix_experiment_runs_status", table_name="experiment_runs")
    op.drop_index(
        op.f("ix_experiment_runs_experiment_id"),
        table_name="experiment_runs",
    )
    op.drop_table("experiment_runs")
    op.drop_index(
        op.f("ix_experiments_prompt_version_id"),
        table_name="experiments",
    )
    op.drop_index("ix_experiments_created_at", table_name="experiments")
    op.drop_table("experiments")
