"""PostgreSQL outbox исходящих уведомлений."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import UTCDateTime


class NotificationOutbox(Base):
    """Событие, которое notification worker должен доставить во внешний канал."""

    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('telegram')",
            name="ck_notification_outbox_channel",
        ),
        CheckConstraint(
            "event_type IN ("
            "'incident_created', 'incident_resolved', 'incident_closed')",
            name="ck_notification_outbox_event_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'sent', 'failed')",
            name="ck_notification_outbox_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts",
            name="ck_notification_outbox_attempts",
        ),
        CheckConstraint(
            "(status = 'running' AND worker_id IS NOT NULL "
            "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'running' AND worker_id IS NULL "
            "AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_notification_outbox_lease_state",
        ),
        CheckConstraint(
            "(status = 'sent' AND sent_at IS NOT NULL "
            "AND external_message_id IS NOT NULL) "
            "OR (status <> 'sent' AND sent_at IS NULL "
            "AND external_message_id IS NULL)",
            name="ck_notification_outbox_sent_state",
        ),
        UniqueConstraint(
            "channel",
            "incident_event_id",
            name="uq_notification_outbox_channel_event",
        ),
        Index(
            "ix_notification_outbox_status_retry",
            "status",
            "next_retry_at",
        ),
        Index(
            "ix_notification_outbox_status_lease",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(
        String(20),
        default="telegram",
        server_default="telegram",
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    incident_event_id: Mapped[int] = mapped_column(
        ForeignKey("incident_events.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    worker_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
        nullable=False,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
