from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incidents.models import (
    Incident,
    IncidentDeviation,
    IncidentEvent,
)
from app.monitoring.models import EquipmentDeviation

logger = structlog.get_logger(__name__)


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress", "closed"},
    "in_progress": {"resolved", "open", "closed"},
    "resolved": {"closed", "in_progress"},
    "closed": {"open"},
}


class InvalidTransitionError(ValueError):
    """Недопустимый переход статуса инцидента."""


class DeviationNotFoundError(ValueError):
    """Отклонение для привязки к инциденту не найдено."""


def create_incident(
    db: Session,
    *,
    equipment_id: int,
    title: str,
    description: str | None = None,
    severity: str = "medium",
    assigned_to: str | None = None,
) -> Incident:
    """Создаёт инцидент и пишет событие 'created'."""
    incident = Incident(
        equipment_id=equipment_id,
        title=title,
        description=description,
        severity=severity,
        assigned_to=assigned_to,
        status="open",
    )
    db.add(incident)
    db.flush()

    db.add(
        IncidentEvent(
            incident_id=incident.id,
            event_type="created",
            payload={"severity": severity, "title": title},
        )
    )
    db.commit()
    db.refresh(incident)

    logger.info(
        "incident_created",
        incident_id=incident.id,
        equipment_id=equipment_id,
        severity=severity,
    )
    return incident


def change_status(
    db: Session,
    incident: Incident,
    new_status: str,
    actor: str | None = None,
) -> Incident:
    """Меняет статус с валидацией перехода и пишет событие."""
    if new_status == incident.status:
        return incident

    if new_status not in ALLOWED_TRANSITIONS.get(incident.status, set()):
        logger.warning(
            "incident_invalid_transition",
            incident_id=incident.id,
            from_status=incident.status,
            to_status=new_status,
        )
        raise InvalidTransitionError(
            f"Недопустимый переход: {incident.status} → {new_status}",
        )

    old_status = incident.status
    incident.status = new_status

    if new_status == "resolved":
        incident.resolved_at = datetime.now(UTC)
    elif new_status in {"open", "in_progress"}:
        incident.resolved_at = None

    db.add(
        IncidentEvent(
            incident_id=incident.id,
            event_type="status_changed",
            payload={
                "from": old_status,
                "to": new_status,
                "actor": actor or "system",
            },
        )
    )
    db.commit()
    db.refresh(incident)

    logger.info(
        "incident_status_changed",
        incident_id=incident.id,
        from_status=old_status,
        to_status=new_status,
        actor=actor,
    )
    return incident


def assign(
    db: Session,
    incident: Incident,
    assignee: str | None,
    actor: str | None = None,
) -> Incident:
    """Назначает/снимает исполнителя с событием."""
    old = incident.assigned_to
    if old == assignee:
        return incident

    incident.assigned_to = assignee
    db.add(
        IncidentEvent(
            incident_id=incident.id,
            event_type="assigned",
            payload={"from": old, "to": assignee, "actor": actor or "system"},
        )
    )
    db.commit()
    db.refresh(incident)
    return incident


def link_deviation(
    db: Session,
    incident: Incident,
    deviation_id: int,
) -> None:
    """Привязывает отклонение (идемпотентно)."""
    if db.get(EquipmentDeviation, deviation_id) is None:
        raise DeviationNotFoundError("Отклонение не найдено")

    existing = db.scalar(
        select(IncidentDeviation).where(
            IncidentDeviation.deviation_id == deviation_id,
        ),
    )
    if existing is not None:
        if existing.incident_id == incident.id:
            return
        raise ValueError(
            f"Отклонение {deviation_id} уже привязано "
            f"к инциденту {existing.incident_id}",
        )

    db.add(
        IncidentDeviation(
            incident_id=incident.id,
            deviation_id=deviation_id,
        )
    )
    db.add(
        IncidentEvent(
            incident_id=incident.id,
            event_type="deviation_linked",
            payload={"deviation_id": deviation_id},
        )
    )
    db.commit()

    logger.info(
        "incident_deviation_linked",
        incident_id=incident.id,
        deviation_id=deviation_id,
    )
