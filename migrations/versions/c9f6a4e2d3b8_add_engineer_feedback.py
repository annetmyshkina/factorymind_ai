"""add engineer feedback and confirmed incident resolutions

Revision ID: c9f6a4e2d3b8
Revises: b8e5f3d1c2a7
Create Date: 2026-11-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "c9f6a4e2d3b8"
down_revision: str | Sequence[str] | None = "b8e5f3d1c2a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable feedback, current resolutions and their audit log."""
    op.create_table(
        "incident_analysis_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column(
            "actor_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating IN ('helpful', 'unhelpful', 'incorrect')",
            name="ck_incident_analysis_feedback_rating",
        ),
        sa.CheckConstraint(
            "actor_verified = false",
            name="ck_incident_analysis_feedback_actor_unverified",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["incident_analyses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incident_analysis_feedback_analysis_created",
        "incident_analysis_feedback",
        ["analysis_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "incident_resolutions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=True),
        sa.Column("checks_performed", sa.JSON(), nullable=False),
        sa.Column("confirmed_cause", sa.Text(), nullable=True),
        sa.Column("actions_taken", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column(
            "actor_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "confirmed_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_incident_resolutions_revision",
        ),
        sa.CheckConstraint(
            "(is_active AND revoked_at IS NULL) "
            "OR (NOT is_active AND revoked_at IS NOT NULL)",
            name="ck_incident_resolutions_active_state",
        ),
        sa.CheckConstraint(
            "actor_verified = false",
            name="ck_incident_resolutions_actor_unverified",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["incident_analyses.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )

    op.create_table(
        "incident_resolution_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resolution_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column(
            "actor_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "before_snapshot",
            sa.JSON(none_as_null=True),
            nullable=True,
        ),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('confirmed', 'corrected', 'revoked')",
            name="ck_incident_resolution_events_type",
        ),
        sa.CheckConstraint(
            "after_snapshot IS NOT NULL",
            name="ck_incident_resolution_events_after_snapshot",
        ),
        sa.CheckConstraint(
            "event_type = 'confirmed' OR before_snapshot IS NOT NULL",
            name="ck_incident_resolution_events_before_snapshot",
        ),
        sa.CheckConstraint(
            "actor_verified = false",
            name="ck_incident_resolution_events_actor_unverified",
        ),
        sa.ForeignKeyConstraint(
            ["resolution_id"],
            ["incident_resolutions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incident_resolution_events_resolution_created",
        "incident_resolution_events",
        ["resolution_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop engineer feedback and confirmed resolution history."""
    op.drop_index(
        "ix_incident_resolution_events_resolution_created",
        table_name="incident_resolution_events",
    )
    op.drop_table("incident_resolution_events")
    op.drop_table("incident_resolutions")
    op.drop_index(
        "ix_incident_analysis_feedback_analysis_created",
        table_name="incident_analysis_feedback",
    )
    op.drop_table("incident_analysis_feedback")
