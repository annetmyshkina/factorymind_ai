"""add equipment api keys

Revision ID: 7b2e6a9c1d4f
Revises: 4c8a1d7e2f90
Create Date: 2026-11-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

revision: str = "7b2e6a9c1d4f"
down_revision: str | Sequence[str] | None = "4c8a1d7e2f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create revocable credentials scoped to one equipment record."""
    op.create_table(
        "equipment_api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_id", sa.String(length=16), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", UTCDateTime(), nullable=True),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "(is_active AND revoked_at IS NULL) "
            "OR (NOT is_active AND revoked_at IS NOT NULL)",
            name="ck_equipment_api_keys_revocation_state",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_id", name="uq_equipment_api_keys_key_id"),
    )
    op.create_index(
        "ix_equipment_api_keys_equipment_id",
        "equipment_api_keys",
        ["equipment_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove equipment API keys."""
    op.drop_index(
        "ix_equipment_api_keys_equipment_id",
        table_name="equipment_api_keys",
    )
    op.drop_table("equipment_api_keys")
