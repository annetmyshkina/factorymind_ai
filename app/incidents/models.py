from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import UTCDateTime

if TYPE_CHECKING:
    from app.equipment.models import Equipment
    from app.monitoring.models import EquipmentDeviation


class Incident(Base):
    """Инцидент — рабочий процесс устранения отклонения."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="ck_incidents_status",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_incidents_severity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="open",
        server_default="open",
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        server_default="medium",
        nullable=False,
    )
    assigned_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )

    equipment: Mapped["Equipment"] = relationship(lazy="raise")

    deviations: Mapped[list["EquipmentDeviation"]] = relationship(
        secondary="incident_deviations",
        lazy="raise",
    )
    events: Mapped[list["IncidentEvent"]] = relationship(
        back_populates="incident",
        lazy="raise",
    )

    @property
    def equipment_code(self) -> str:
        """Код оборудования."""
        return self.equipment.code


class IncidentDeviation(Base):
    """Связь инцидента с отклонением (M2M, одно отклонение — один инцидент)."""

    __tablename__ = "incident_deviations"
    __table_args__ = (
        UniqueConstraint(
            "deviation_id",
            name="uq_incident_deviations_deviation_id",
        ),
    )

    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    deviation_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_deviations.id", ondelete="CASCADE"),
        primary_key=True,
    )


class IncidentEvent(Base):
    """Событие истории инцидента (аудит)."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    incident: Mapped["Incident"] = relationship(
        back_populates="events",
        lazy="raise",
    )
