"""add durable experiment worker queue

Revision ID: c8f3a2d1e6b7
Revises: a4e9c1f7b2d8
Create Date: 2026-11-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "c8f3a2d1e6b7"
down_revision: str | Sequence[str] | None = "a4e9c1f7b2d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add leases, retry scheduling, attempt history and final-call ownership."""
    op.add_column(
        "experiment_runs",
        sa.Column("worker_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "experiment_runs",
        sa.Column("lease_token", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "experiment_runs",
        sa.Column("lease_expires_at", UTCDateTime(), nullable=True),
    )
    op.add_column(
        "experiment_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "experiment_runs",
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.add_column(
        "experiment_runs",
        sa.Column("next_retry_at", UTCDateTime(), nullable=True),
    )
    op.add_column(
        "experiment_runs",
        sa.Column("final_call_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_calls",
        sa.Column("experiment_attempt", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_calls",
        sa.Column("lease_token", sa.Uuid(), nullable=True),
    )

    # Preserve the fact that a legacy running job had already been attempted.
    op.execute(
        """
        UPDATE experiment_runs
        SET attempt_count = CASE WHEN status = 'pending' THEN 0 ELSE 1 END
        """,
    )
    op.execute(
        """
        UPDATE llm_calls
        SET experiment_attempt = 1
        WHERE experiment_run_id IS NOT NULL
        """,
    )

    op.drop_constraint(
        "ck_experiment_runs_status",
        "experiment_runs",
        type_="check",
    )
    op.execute(
        "UPDATE experiment_runs SET status = 'completed' WHERE status = 'succeeded'"
    )
    op.execute(
        """
        UPDATE experiment_runs
        SET status = 'pending', finished_at = NULL
        WHERE status = 'running'
        """,
    )
    op.execute(
        """
        UPDATE experiment_runs
        SET finished_at = COALESCE(finished_at, now())
        WHERE status IN ('completed', 'failed')
        """,
    )
    op.execute(
        """
        UPDATE experiment_runs AS run
        SET final_call_id = (
            SELECT call.id
            FROM llm_calls AS call
            WHERE call.experiment_run_id = run.id
            ORDER BY call.id DESC
            LIMIT 1
        )
        WHERE run.status IN ('completed', 'failed')
        """,
    )

    op.alter_column(
        "experiment_runs",
        "attempt_count",
        existing_type=sa.Integer(),
        server_default="0",
        nullable=False,
    )
    op.create_foreign_key(
        "fk_experiment_runs_final_call_id",
        "experiment_runs",
        "llm_calls",
        ["final_call_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_experiment_runs_status",
        "experiment_runs",
        "status IN ('pending', 'running', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_experiment_runs_attempts",
        "experiment_runs",
        "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts",
    )
    op.create_check_constraint(
        "ck_experiment_runs_lease_state",
        "experiment_runs",
        "(status = 'running' AND worker_id IS NOT NULL "
        "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
        "OR (status <> 'running' AND worker_id IS NULL "
        "AND lease_token IS NULL AND lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_experiment_runs_finished_state",
        "experiment_runs",
        "(status IN ('pending', 'running') AND finished_at IS NULL) "
        "OR (status IN ('completed', 'failed') AND finished_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_experiment_runs_completed_call",
        "experiment_runs",
        "status <> 'completed' OR final_call_id IS NOT NULL",
    )
    op.create_index(
        "ix_experiment_runs_status_retry",
        "experiment_runs",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "ix_experiment_runs_status_lease",
        "experiment_runs",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_llm_calls_experiment_attempt",
        "llm_calls",
        ["experiment_run_id", "experiment_attempt"],
        unique=False,
    )


def downgrade() -> None:
    """Restore the synchronous experiment schema."""
    op.drop_index("ix_llm_calls_experiment_attempt", table_name="llm_calls")
    op.drop_index("ix_experiment_runs_status_lease", table_name="experiment_runs")
    op.drop_index("ix_experiment_runs_status_retry", table_name="experiment_runs")
    op.drop_constraint(
        "ck_experiment_runs_completed_call",
        "experiment_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_experiment_runs_finished_state",
        "experiment_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_experiment_runs_lease_state",
        "experiment_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_experiment_runs_attempts",
        "experiment_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_experiment_runs_status",
        "experiment_runs",
        type_="check",
    )
    op.execute(
        "UPDATE experiment_runs SET status = 'succeeded' WHERE status = 'completed'"
    )
    op.create_check_constraint(
        "ck_experiment_runs_status",
        "experiment_runs",
        "status IN ('pending', 'running', 'succeeded', 'failed')",
    )
    op.drop_constraint(
        "fk_experiment_runs_final_call_id",
        "experiment_runs",
        type_="foreignkey",
    )
    op.drop_column("llm_calls", "lease_token")
    op.drop_column("llm_calls", "experiment_attempt")
    op.drop_column("experiment_runs", "final_call_id")
    op.drop_column("experiment_runs", "next_retry_at")
    op.drop_column("experiment_runs", "max_attempts")
    op.drop_column("experiment_runs", "attempt_count")
    op.drop_column("experiment_runs", "lease_expires_at")
    op.drop_column("experiment_runs", "lease_token")
    op.drop_column("experiment_runs", "worker_id")
