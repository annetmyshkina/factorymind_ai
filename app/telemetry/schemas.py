from datetime import UTC

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class TelemetryCreate(BaseModel):
    """Данные для создания показаний."""

    temperature_c: float = Field(allow_inf_nan=False)
    vibration_mm_s: float = Field(ge=0, allow_inf_nan=False)

    ambient_temperature_c: float | None = Field(
        default=None,
        allow_inf_nan=False,
    )
    suction_pressure_kpa_g: float | None = Field(
        default=None,
        allow_inf_nan=False,
    )
    discharge_pressure_kpa_g: float | None = Field(
        default=None,
        allow_inf_nan=False,
    )
    compressor_current_a: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    compressor_vsd_frequency_hz: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    coolant_flow_rate_m3_h: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    compressor_running: bool | None = None


class TelemetryResponse(BaseModel):
    """Данные показаний, возвращаемые клиенту."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    measured_at: AwareDatetime

    temperature_c: float
    vibration_mm_s: float

    ambient_temperature_c: float | None
    suction_pressure_kpa_g: float | None
    discharge_pressure_kpa_g: float | None
    compressor_current_a: float | None
    compressor_vsd_frequency_hz: float | None
    coolant_flow_rate_m3_h: float | None
    compressor_running: bool | None


class TelemetryHistoryParams(BaseModel):
    """Параметры фильтрации истории показаний."""

    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None

    @field_validator("since", "until")
    @classmethod
    def normalize_to_utc(
        cls,
        value: AwareDatetime | None,
    ) -> AwareDatetime | None:
        """Приводит даты с часовым поясом к UTC."""

        if value is None:
            return None

        return value.astimezone(UTC)
