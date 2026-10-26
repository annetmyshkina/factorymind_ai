from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.equipment.models import Equipment
from app.telemetry.models import EquipmentTelemetry
from app.telemetry.schemas import TelemetryCreate, TelemetryResponse

router = APIRouter(
    prefix="/equipment",
    tags=["Telemetry"],
)


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
    """Создаёт запись о данных датчика."""

    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    telemetry = EquipmentTelemetry(
        equipment_id=equipment_id, **telemetry_data.model_dump()
    )

    db.add(telemetry)
    db.commit()
    db.refresh(telemetry)

    return telemetry
