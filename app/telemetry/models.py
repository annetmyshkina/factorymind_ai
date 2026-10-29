from datetime import UTC, datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import UTCDateTime


class EquipmentTelemetry(Base):
    __tablename__ = "equipment_telemetry"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    measured_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    temperature_c: Mapped[float]
    vibration_mm_s: Mapped[float]

    ambient_temperature_c: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    suction_pressure_kpa_g: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    discharge_pressure_kpa_g: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    compressor_current_a: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    compressor_vsd_frequency_hz: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    coolant_flow_rate_m3_h: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    compressor_running: Mapped[bool | None] = mapped_column(
        nullable=True,
    )


class ProcessedMQTTEvent(Base):
    """Обработанное MQTT-сообщение (идемпотентность)."""

    __tablename__ = "processed_mqtt_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
