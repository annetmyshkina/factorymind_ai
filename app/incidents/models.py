from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
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


class IncidentAnalysis(Base):
    """Неизменяемый структурированный результат AI-анализа инцидента."""

    __tablename__ = "incident_analyses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'insufficient')",
            name="ck_incident_analyses_status",
        ),
        CheckConstraint(
            "(status = 'completed' AND llm_call_id IS NOT NULL) "
            "OR (status = 'insufficient' AND llm_call_id IS NULL)",
            name="ck_incident_analyses_call_state",
        ),
        Index("ix_incident_analyses_incident_created", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    llm_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class IncidentAnalysisSource(Base):
    """Фрагмент документа, фактически переданный конкретному анализу."""

    __tablename__ = "incident_analysis_sources"
    __table_args__ = (
        CheckConstraint("rank > 0", name="ck_incident_analysis_sources_rank"),
        CheckConstraint("score >= 0", name="ck_incident_analysis_sources_score"),
        UniqueConstraint(
            "analysis_id",
            "rank",
            name="uq_incident_analysis_sources_analysis_rank",
        ),
    )

    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("incident_analyses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_document_chunks.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)


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
