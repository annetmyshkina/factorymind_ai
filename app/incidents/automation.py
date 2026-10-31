"""Автоматическое создание инцидентов по отклонениям мониторинга."""

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incidents.models import Incident
from app.incidents.service import add_deviation_link, add_incident
from app.monitoring.metrics import METRICS
from app.monitoring.models import EquipmentDeviation

logger = structlog.get_logger(__name__)

# Инцидент считается активным, пока он не решён и не закрыт.
ACTIVE_INCIDENT_STATUSES: tuple[str, ...] = ("open", "in_progress")

# Severity автоинцидента по метрике; для остальных метрик — medium.
SEVERITY_BY_METRIC: dict[str, str] = {
    "temperature_c": "critical",
    "vibration_mm_s": "high",
}

DEFAULT_INCIDENT_SEVERITY = "medium"


def find_active_incident(
    db: Session,
    equipment_id: int,
) -> Incident | None:
    """Возвращает последний активный инцидент оборудования, если он есть."""
    return db.scalar(
        select(Incident)
        .where(
            Incident.equipment_id == equipment_id,
            Incident.status.in_(ACTIVE_INCIDENT_STATUSES),
        )
        .order_by(Incident.created_at.desc(), Incident.id.desc())
        .limit(1),
    )


def ensure_incident_for_deviation(
    db: Session,
    deviation: EquipmentDeviation,
) -> Incident:
    """Создаёт инцидент по отклонению или привязывает его к активному.

    Не коммитит транзакцию: отклонение, инцидент и события сохраняются
    вместе с телеметрией вызывающей стороны.
    """
    db.flush()

    incident = find_active_incident(db, deviation.equipment_id)

    if incident is None:
        metric = METRICS[deviation.metric_name]
        incident = add_incident(
            db,
            equipment_id=deviation.equipment_id,
            title=f"{metric.name}: {deviation.observed_value:g} {metric.unit}",
            description=deviation.message,
            severity=SEVERITY_BY_METRIC.get(
                deviation.metric_name,
                DEFAULT_INCIDENT_SEVERITY,
            ),
        )
        logger.info(
            "incident_auto_created",
            incident_id=incident.id,
            equipment_id=deviation.equipment_id,
            deviation_id=deviation.id,
            metric_name=deviation.metric_name,
            severity=incident.severity,
        )

    add_deviation_link(db, incident, deviation.id)
    return incident
