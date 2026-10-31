from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.equipment.models import Equipment
from app.incidents.automation import ensure_incident_for_deviation
from app.monitoring.service import (
    InvalidMonitoringRuleError,
    evaluate_telemetry,
)
from app.telemetry.models import EquipmentTelemetry
from app.telemetry.schemas import (
    TelemetryCreate,
    TelemetryHistoryParams,
    TelemetryResponse,
)

router = APIRouter(
    prefix="/equipment",
    tags=["Telemetry"],
)

logger = structlog.get_logger(__name__)

TelemetryHistoryQuery = Annotated[
    TelemetryHistoryParams,
    Depends(),
]


@router.post(
    "/{equipment_id}/telemetry",
    response_model=TelemetryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_telemetry(
    equipment_id: int,
    telemetry_data: TelemetryCreate,
    db: Session = Depends(get_db),
) -> TelemetryResponse:
    """Создаёт запись о данных датчика и проверяет правила мониторинга."""

    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    try:
        telemetry = EquipmentTelemetry(
            equipment_id=equipment_id,
            **telemetry_data.model_dump(),
        )
        db.add(telemetry)
        db.flush()

        deviations = evaluate_telemetry(db, telemetry)
        for deviation in deviations:
            ensure_incident_for_deviation(db, deviation)

        db.commit()
        db.refresh(telemetry)
        return telemetry

    except InvalidMonitoringRuleError:
        db.rollback()
        logger.exception(
            "monitoring_rule_error",
            equipment_id=equipment_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка конфигурации правил мониторинга",
        ) from None

    except Exception:
        db.rollback()
        raise


@router.get(
    "/{equipment_id}/telemetry",
    response_model=list[TelemetryResponse],
)
def get_telemetry(
    equipment_id: int,
    params: TelemetryHistoryQuery,
    db: Session = Depends(get_db),
) -> list[TelemetryResponse]:
    """Возвращает историю показаний оборудования."""

    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    if (
        params.since is not None
        and params.until is not None
        and params.since > params.until
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Дата начала периода не может быть позже даты окончания",
        )

    query = (
        select(EquipmentTelemetry)
        .where(EquipmentTelemetry.equipment_id == equipment_id)
        .order_by(
            EquipmentTelemetry.measured_at.desc(),
            EquipmentTelemetry.id.desc(),
        )
    )

    if params.since is not None:
        query = query.where(
            EquipmentTelemetry.measured_at >= params.since,
        )

    if params.until is not None:
        query = query.where(
            EquipmentTelemetry.measured_at <= params.until,
        )

    query = query.limit(params.limit).offset(params.offset)

    return list(db.scalars(query).all())
