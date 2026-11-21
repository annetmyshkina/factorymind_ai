"""add durable Telegram notification outbox

Revision ID: f7d1b4c9e2a6
Revises: e2a7c4d9b1f3
Create Date: 2026-11-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

revision: str = "f7d1b4c9e2a6"
down_revision: str | Sequence[str] | None = "e2a7c4d9b1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create leased and retryable notification outbox."""
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=20),
            server_default="telegram",
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("incident_event_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(length=200), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", UTCDateTime(), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
        sa.Column("next_retry_at", UTCDateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("external_message_id", sa.String(length=100), nullable=True),
        sa.Column("sent_at", UTCDateTime(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel IN ('telegram')",
            name="ck_notification_outbox_channel",
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'incident_created', 'incident_resolved', 'incident_closed')",
            name="ck_notification_outbox_event_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'sent', 'failed')",
            name="ck_notification_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts",
            name="ck_notification_outbox_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND worker_id IS NOT NULL "
            "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'running' AND worker_id IS NULL "
            "AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_notification_outbox_lease_state",
        ),
        sa.CheckConstraint(
            "(status = 'sent' AND sent_at IS NOT NULL "
            "AND external_message_id IS NOT NULL) "
            "OR (status <> 'sent' AND sent_at IS NULL "
            "AND external_message_id IS NULL)",
            name="ck_notification_outbox_sent_state",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_event_id"],
            ["incident_events.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel",
            "incident_event_id",
            name="uq_notification_outbox_channel_event",
        ),
    )
    op.create_index(
        op.f("ix_notification_outbox_incident_id"),
        "notification_outbox",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_outbox_incident_event_id"),
        "notification_outbox",
        ["incident_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_outbox_status_retry",
        "notification_outbox",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_outbox_status_lease",
        "notification_outbox",
        ["status", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove notification outbox."""
    op.drop_index(
        "ix_notification_outbox_status_lease",
        table_name="notification_outbox",
    )
    op.drop_index(
        "ix_notification_outbox_status_retry",
        table_name="notification_outbox",
    )
    op.drop_index(
        op.f("ix_notification_outbox_incident_event_id"),
        table_name="notification_outbox",
    )
    op.drop_index(
        op.f("ix_notification_outbox_incident_id"),
        table_name="notification_outbox",
    )
    op.drop_table("notification_outbox")
