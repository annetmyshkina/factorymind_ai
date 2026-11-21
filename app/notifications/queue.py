"""Захват, retry и lease-защита Telegram outbox."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.notifications.errors import TelegramDeliveryError
from app.notifications.models import NotificationOutbox
from app.notifications.telegram import TelegramClient
from app.observability.metrics import (
    NOTIFICATION_DELIVERIES,
    NOTIFICATION_LEASE_RECOVERIES,
    set_notification_queue_counts,
)

logger = structlog.get_logger(__name__)

SessionFactory = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class ClaimedNotification:
    item_id: int
    worker_id: str
    lease_token: UUID
    attempt: int


@dataclass(frozen=True, slots=True)
class NotificationInput:
    event_type: str
    payload: dict[str, object]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _database_now(db: Session) -> datetime:
    value = db.scalar(select(func.now()))
    if not isinstance(value, datetime):
        raise RuntimeError("База данных не вернула текущее время")
    return _utc(value)


def _clear_lease(item: NotificationOutbox) -> None:
    item.worker_id = None
    item.lease_token = None
    item.lease_expires_at = None


def claim_next_notification(
    db: Session,
    worker_id: str,
    *,
    lease_seconds: int,
) -> ClaimedNotification | None:
    """Атомарно захватывает готовое уведомление через SKIP LOCKED."""
    item = db.scalar(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status == "pending",
            NotificationOutbox.attempt_count < NotificationOutbox.max_attempts,
            or_(
                NotificationOutbox.next_retry_at.is_(None),
                NotificationOutbox.next_retry_at <= func.now(),
            ),
        )
        .order_by(
            func.coalesce(
                NotificationOutbox.next_retry_at,
                NotificationOutbox.created_at,
            ),
            NotificationOutbox.id,
        )
        .with_for_update(skip_locked=True)
        .limit(1),
    )
    if item is None:
        db.rollback()
        return None

    token = uuid4()
    now = _database_now(db)
    item.status = "running"
    item.worker_id = worker_id
    item.lease_token = token
    item.lease_expires_at = now + timedelta(seconds=lease_seconds)
    item.attempt_count += 1
    item.next_retry_at = None
    item.error = None
    db.commit()

    logger.info(
        "notification_claimed",
        notification_id=item.id,
        worker_id=worker_id,
        attempt=item.attempt_count,
    )
    return ClaimedNotification(
        item_id=item.id,
        worker_id=worker_id,
        lease_token=token,
        attempt=item.attempt_count,
    )


def recover_expired_notifications(db: Session) -> int:
    """Возвращает просроченные lease в очередь либо завершает их ошибкой."""
    items = list(
        db.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == "running",
                NotificationOutbox.lease_expires_at <= func.now(),
            )
            .order_by(NotificationOutbox.id)
            .with_for_update(skip_locked=True),
        ),
    )
    if not items:
        db.rollback()
        return 0

    now = _database_now(db)
    outcomes = {"requeued": 0, "failed": 0}
    for item in items:
        _clear_lease(item)
        item.error = "Истёк lease notification worker-а"
        if item.attempt_count >= item.max_attempts:
            outcomes["failed"] += 1
            item.status = "failed"
            item.next_retry_at = None
        else:
            outcomes["requeued"] += 1
            item.status = "pending"
            item.next_retry_at = now
    db.commit()
    for outcome, count in outcomes.items():
        if count:
            NOTIFICATION_LEASE_RECOVERIES.labels(outcome=outcome).inc(count)
    logger.warning("notification_leases_recovered", count=len(items))
    return len(items)


def _load_input(
    db: Session,
    claim: ClaimedNotification,
) -> NotificationInput | None:
    item = db.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.id == claim.item_id,
            NotificationOutbox.status == "running",
            NotificationOutbox.worker_id == claim.worker_id,
            NotificationOutbox.lease_token == claim.lease_token,
            NotificationOutbox.lease_expires_at > func.now(),
        ),
    )
    if item is None:
        return None
    return NotificationInput(
        event_type=item.event_type,
        payload=dict(item.payload),
    )


def _owned_item(
    db: Session,
    claim: ClaimedNotification,
) -> NotificationOutbox | None:
    return db.scalar(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.id == claim.item_id,
            NotificationOutbox.status == "running",
            NotificationOutbox.worker_id == claim.worker_id,
            NotificationOutbox.lease_token == claim.lease_token,
            NotificationOutbox.lease_expires_at > func.now(),
        )
        .with_for_update(),
    )


def render_notification(
    notification: NotificationInput,
    *,
    public_app_base_url: str | None = None,
) -> str:
    """Строит plain-text сообщение из неизменяемого снимка outbox."""
    headings = {
        "incident_created": "Новый автоматический инцидент",
        "incident_resolved": "Инцидент разрешён",
        "incident_closed": "Инцидент закрыт",
    }
    payload = notification.payload
    lines = [
        f"FactoryMind AI — {headings[notification.event_type]}",
        f"Оборудование: {payload['equipment_code']}",
        f"Инцидент #{payload['incident_id']}: {payload['title']}",
        f"Критичность: {str(payload['severity']).upper()}",
        f"Статус: {payload['status']}",
    ]
    if public_app_base_url:
        base_url = public_app_base_url.rstrip("/")
        lines.append(
            f"Карточка: {base_url}/#incidents?filter=all&incident="
            f"{payload['incident_id']}",
        )
    return "\n".join(lines)


def _finalize_success(
    db: Session,
    claim: ClaimedNotification,
    external_message_id: str,
) -> bool:
    item = _owned_item(db, claim)
    if item is None:
        db.rollback()
        NOTIFICATION_DELIVERIES.labels(outcome="stale_lease_rejected").inc()
        return False
    item.status = "sent"
    item.external_message_id = external_message_id
    item.sent_at = _database_now(db)
    item.next_retry_at = None
    item.error = None
    _clear_lease(item)
    db.commit()
    NOTIFICATION_DELIVERIES.labels(outcome="sent").inc()
    logger.info(
        "notification_sent",
        notification_id=item.id,
        attempt=claim.attempt,
    )
    return True


def _finalize_failure(
    db: Session,
    claim: ClaimedNotification,
    *,
    message: str,
    retryable: bool,
    retry_base_seconds: int,
) -> bool:
    item = _owned_item(db, claim)
    if item is None:
        db.rollback()
        NOTIFICATION_DELIVERIES.labels(outcome="stale_lease_rejected").inc()
        return False

    item.error = message
    _clear_lease(item)
    if retryable and item.attempt_count < item.max_attempts:
        delay = retry_base_seconds * (2 ** (item.attempt_count - 1))
        item.status = "pending"
        item.next_retry_at = _database_now(db) + timedelta(seconds=delay)
        outcome = "retry_scheduled"
    else:
        item.status = "failed"
        item.next_retry_at = None
        outcome = "failed"
    db.commit()
    NOTIFICATION_DELIVERIES.labels(outcome=outcome).inc()
    logger.warning(
        "notification_delivery_failed",
        notification_id=item.id,
        attempt=claim.attempt,
        retryable=retryable,
        outcome=outcome,
    )
    return True


def execute_claimed_notification(
    session_factory: SessionFactory,
    claim: ClaimedNotification,
    client: TelegramClient,
    *,
    notification_settings: Settings = settings,
) -> bool:
    """Вызывает Telegram вне транзакции и фиксирует только актуальный lease."""
    try:
        with session_factory() as db:
            notification = _load_input(db, claim)
        if notification is None:
            return False
        text = render_notification(
            notification,
            public_app_base_url=notification_settings.public_app_base_url,
        )
        external_message_id = client.send_message(text)
    except TelegramDeliveryError as exc:
        with session_factory() as db:
            return _finalize_failure(
                db,
                claim,
                message=str(exc),
                retryable=exc.retryable,
                retry_base_seconds=(
                    notification_settings.notification_retry_base_seconds
                ),
            )
    except Exception:
        logger.exception(
            "notification_attempt_unexpected_error",
            notification_id=claim.item_id,
            attempt=claim.attempt,
        )
        with session_factory() as db:
            return _finalize_failure(
                db,
                claim,
                message="Неожиданная ошибка доставки",
                retryable=True,
                retry_base_seconds=(
                    notification_settings.notification_retry_base_seconds
                ),
            )

    with session_factory() as db:
        return _finalize_success(db, claim, external_message_id)


def process_next_notification(
    session_factory: SessionFactory,
    worker_id: str,
    client: TelegramClient,
    *,
    notification_settings: Settings = settings,
) -> bool:
    """Обрабатывает одно уведомление; False означает пустую очередь."""
    with session_factory() as db:
        claim = claim_next_notification(
            db,
            worker_id,
            lease_seconds=notification_settings.notification_worker_lease_seconds,
        )
    if claim is None:
        return False
    execute_claimed_notification(
        session_factory,
        claim,
        client,
        notification_settings=notification_settings,
    )
    return True


def update_queue_metrics(db: Session) -> None:
    counts = {
        status: count
        for status, count in db.execute(
            select(NotificationOutbox.status, func.count()).group_by(
                NotificationOutbox.status,
            ),
        )
    }
    set_notification_queue_counts(counts)
