"""add prompt_versions

Revision ID: d5a1c7e9f2b4
Revises: b3f1c9d2a4e6
Create Date: 2026-11-03 12:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "d5a1c7e9f2b4"
down_revision: str | Sequence[str] | None = "b3f1c9d2a4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "name",
            "version",
            name="uq_prompt_versions_name_version",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("prompt_versions")
