import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.equipment.models import Equipment
from app.monitoring.models import EquipmentDeviation, MonitoringRule
from app.monitoring.schemas import (
    EquipmentDeviationResponse,
    MonitoringRuleCreate,
    MonitoringRuleResponse,
)

router = APIRouter(
    prefix="/equipment",
    tags=["Monitoring"],
)

logger = structlog.get_logger(__name__)


@router.post(
    "/{equipment_id}/monitoring-rules",
    response_model=MonitoringRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_monitoring_rule(
    equipment_id: int,
    rule_data: MonitoringRuleCreate,
    db: Session = Depends(get_db),
) -> MonitoringRuleResponse:
    """Создаёт правило мониторинга для оборудования."""
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    try:
        rule = MonitoringRule(
            equipment_id=equipment_id,
            **rule_data.model_dump(),
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
    except Exception:
        db.rollback()
        logger.exception(
            "monitoring_rule_creation_error",
            equipment_id=equipment_id,
        )
        raise

    return rule


@router.get(
    "/{equipment_id}/monitoring-rules",
    response_model=list[MonitoringRuleResponse],
)
def list_monitoring_rules(
    equipment_id: int,
    db: Session = Depends(get_db),
) -> list[MonitoringRuleResponse]:
    """Возвращает правила мониторинга оборудования."""
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    rules = db.scalars(
        select(MonitoringRule)
        .where(MonitoringRule.equipment_id == equipment_id)
        .order_by(MonitoringRule.id),
    ).all()

    return list(rules)


@router.get(
    "/{equipment_id}/deviations",
    response_model=list[EquipmentDeviationResponse],
)
def list_deviations(
    equipment_id: int,
    db: Session = Depends(get_db),
) -> list[EquipmentDeviationResponse]:
    """Возвращает зафиксированные отклонения оборудования."""
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    deviations = db.scalars(
        select(EquipmentDeviation)
        .where(EquipmentDeviation.equipment_id == equipment_id)
        .order_by(EquipmentDeviation.detected_at.desc()),
    ).all()

    return list(deviations)
