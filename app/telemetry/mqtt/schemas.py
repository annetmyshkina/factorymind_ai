from pydantic import AwareDatetime, Field

from app.telemetry.schemas import TelemetryCreate


class MQTTTelemetryMessage(TelemetryCreate):
    """MQTT-конверт с теми же измерениями и валидацией, что и HTTP API."""

    event_id: str = Field(min_length=1, max_length=36)
    equipment_code: str = Field(min_length=1, max_length=50)
    measured_at: AwareDatetime
