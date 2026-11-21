"""Формирование транзакционных outbox-событий для инцидентов."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.equipment.models import Equipment
from app.incidents.models import Incident, IncidentEvent
from app.notifications.models import NotificationOutbox
from app.observability.metrics import NOTIFICATIONS_ENQUEUED

NOTIFIABLE_SEVERITIES = frozenset({"high", "critical"})
NOTIFIABLE_FINAL_STATUSES = frozenset({"resolved", "closed"})
_PENDING_METRICS_KEY = "notification_outbox_event_types"


def _created_event(db: Session, incident_id: int) -> IncidentEvent | None:
    return db.scalar(
        select(IncidentEvent)
        .where(
            IncidentEvent.incident_id == incident_id,
            IncidentEvent.event_type == "created",
        )
        .order_by(IncidentEvent.id)
        .limit(1),
    )


def _was_notifiable_automatic_incident(db: Session, incident_id: int) -> bool:
    event = _created_event(db, incident_id)
    payload = event.payload if event is not None else None
    return bool(
        isinstance(payload, dict)
        and payload.get("source") == "automatic"
        and payload.get("severity") in NOTIFIABLE_SEVERITIES
    )


def _enqueue(
    db: Session,
    *,
    incident: Incident,
    event: IncidentEvent,
    event_type: str,
) -> NotificationOutbox | None:
    if not settings.telegram_notifications_enabled:
        return None

    equipment = db.get(Equipment, incident.equipment_id)
    if equipment is None:
        raise RuntimeError("Оборудование инцидента не найдено")

    item = NotificationOutbox(
        channel="telegram",
        event_type=event_type,
        incident_id=incident.id,
        incident_event_id=event.id,
        payload={
            "incident_id": incident.id,
            "equipment_id": equipment.id,
            "equipment_code": equipment.code,
            "title": incident.title,
            "severity": incident.severity,
            "status": incident.status,
        },
        max_attempts=settings.notification_max_attempts,
    )
    db.add(item)
    db.flush()
    db.info.setdefault(_PENDING_METRICS_KEY, []).append(event_type)
    return item


def observe_committed_notifications(db: Session) -> None:
    """Публикует метрики outbox только после commit вызывающей транзакции."""
    for event_type in db.info.pop(_PENDING_METRICS_KEY, []):
        NOTIFICATIONS_ENQUEUED.labels(event_type=event_type).inc()


def discard_pending_notification_metrics(db: Session) -> None:
    """Удаляет несохранённые метрики после rollback."""
    db.info.pop(_PENDING_METRICS_KEY, None)


def enqueue_created_incident(
    db: Session,
    *,
    incident: Incident,
    event: IncidentEvent,
) -> NotificationOutbox | None:
    """Ставит в очередь новый автоматический high/critical инцидент."""
    if incident.severity not in NOTIFIABLE_SEVERITIES:
        return None
    return _enqueue(
        db,
        incident=incident,
        event=event,
        event_type="incident_created",
    )


def enqueue_final_status(
    db: Session,
    *,
    incident: Incident,
    event: IncidentEvent,
) -> NotificationOutbox | None:
    """Ставит в очередь resolved/closed для ранее оповещаемого инцидента."""
    if (
        incident.status not in NOTIFIABLE_FINAL_STATUSES
        or not _was_notifiable_automatic_incident(db, incident.id)
    ):
        return None
    return _enqueue(
        db,
        incident=incident,
        event=event,
        event_type=f"incident_{incident.status}",
    )
