from pydantic import AwareDatetime, BaseModel, Field


class MQTTTelemetryMessage(BaseModel):
    event_id: str = Field(min_length=1, max_length=36)
    equipment_code: str = Field(min_length=1, max_length=50)
    measured_at: AwareDatetime

    temperature_c: float
    vibration_mm_s: float = Field(ge=0)
    ambient_temperature_c: float | None = None
    suction_pressure_kpa_g: float | None = None
    discharge_pressure_kpa_g: float | None = None
    compressor_current_a: float | None = Field(default=None, ge=0)
    compressor_vsd_frequency_hz: float | None = Field(default=None, ge=0)
    coolant_flow_rate_m3_h: float | None = Field(default=None, ge=0)
    compressor_running: bool | None = None
