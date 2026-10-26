from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TelemetryCreate(BaseModel):
    """Данные для создания показаний."""

    temperature_c: float
    vibration_mm_s: float


class TelemetryResponse(BaseModel):
    """Данные показаний, возвращаемые клиенту."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    measured_at: datetime
    temperature_c: float
    vibration_mm_s: float
