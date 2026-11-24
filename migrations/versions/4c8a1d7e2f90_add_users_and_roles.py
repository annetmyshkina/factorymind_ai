"""add local users and roles

Revision ID: 4c8a1d7e2f90
Revises: f7d1b4c9e2a6
Create Date: 2026-11-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c8a1d7e2f90"
down_revision: str | Sequence[str] | None = "f7d1b4c9e2a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create users whose current role and active flag are checked per request."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
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
            "role IN ('viewer', 'operator', 'engineer', 'admin')",
            name="ck_users_role",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.drop_constraint(
        "ck_incident_analysis_feedback_actor_unverified",
        "incident_analysis_feedback",
        type_="check",
    )
    op.drop_constraint(
        "ck_incident_resolutions_actor_unverified",
        "incident_resolutions",
        type_="check",
    )
    op.drop_constraint(
        "ck_incident_resolution_events_actor_unverified",
        "incident_resolution_events",
        type_="check",
    )


def downgrade() -> None:
    """Remove local users."""
    op.execute(
        sa.text(
            "UPDATE incident_resolution_events SET actor_verified = false "
            "WHERE actor_verified = true",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE incident_resolutions SET actor_verified = false "
            "WHERE actor_verified = true",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE incident_analysis_feedback SET actor_verified = false "
            "WHERE actor_verified = true",
        ),
    )
    op.create_check_constraint(
        "ck_incident_resolution_events_actor_unverified",
        "incident_resolution_events",
        "actor_verified = false",
    )
    op.create_check_constraint(
        "ck_incident_resolutions_actor_unverified",
        "incident_resolutions",
        "actor_verified = false",
    )
    op.create_check_constraint(
        "ck_incident_analysis_feedback_actor_unverified",
        "incident_analysis_feedback",
        "actor_verified = false",
    )
    op.drop_table("users")
