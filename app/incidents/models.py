from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import UTCDateTime

if TYPE_CHECKING:
    from app.equipment.models import Equipment
    from app.monitoring.models import EquipmentDeviation


_resolution_search_index = Index(
    "ix_incident_resolutions_search",
    text("to_tsvector('simple', search_text)"),
    postgresql_using="gin",
).ddl_if(dialect="postgresql")


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


class IncidentAnalysisExperience(Base):
    """Снимок подтверждённого опыта, переданного конкретному анализу."""

    __tablename__ = "incident_analysis_experiences"
    __table_args__ = (
        CheckConstraint("rank > 0", name="ck_incident_analysis_experiences_rank"),
        CheckConstraint("score >= 0", name="ck_incident_analysis_experiences_score"),
        CheckConstraint(
            "resolution_revision > 0",
            name="ck_incident_analysis_experiences_revision",
        ),
        UniqueConstraint(
            "analysis_id",
            "rank",
            name="uq_incident_analysis_experiences_analysis_rank",
        ),
    )

    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("incident_analyses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    resolution_id: Mapped[int] = mapped_column(
        ForeignKey("incident_resolutions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    resolution_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IncidentAnalysisFeedback(Base):
    """Неизменяемая субъективная оценка сохранённого AI-анализа."""

    __tablename__ = "incident_analysis_feedback"
    __table_args__ = (
        CheckConstraint(
            "rating IN ('helpful', 'unhelpful', 'incorrect')",
            name="ck_incident_analysis_feedback_rating",
        ),
        CheckConstraint(
            "actor_verified = false",
            name="ck_incident_analysis_feedback_actor_unverified",
        ),
        Index(
            "ix_incident_analysis_feedback_analysis_created",
            "analysis_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("incident_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class IncidentResolution(Base):
    """Текущий подтверждённый результат диагностики одного инцидента."""

    __tablename__ = "incident_resolutions"
    __table_args__ = (
        CheckConstraint(
            "revision > 0",
            name="ck_incident_resolutions_revision",
        ),
        CheckConstraint(
            "(is_active AND revoked_at IS NULL) "
            "OR (NOT is_active AND revoked_at IS NOT NULL)",
            name="ck_incident_resolutions_active_state",
        ),
        CheckConstraint(
            "actor_verified = false",
            name="ck_incident_resolutions_actor_unverified",
        ),
        _resolution_search_index,
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("incident_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    checks_performed: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confirmed_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    actions_taken: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )


class IncidentResolutionEvent(Base):
    """Неизменяемый аудит подтверждения, исправления и отзыва результата."""

    __tablename__ = "incident_resolution_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('confirmed', 'corrected', 'revoked')",
            name="ck_incident_resolution_events_type",
        ),
        CheckConstraint(
            "after_snapshot IS NOT NULL",
            name="ck_incident_resolution_events_after_snapshot",
        ),
        CheckConstraint(
            "event_type = 'confirmed' OR before_snapshot IS NOT NULL",
            name="ck_incident_resolution_events_before_snapshot",
        ),
        CheckConstraint(
            "actor_verified = false",
            name="ck_incident_resolution_events_actor_unverified",
        ),
        Index(
            "ix_incident_resolution_events_resolution_created",
            "resolution_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resolution_id: Mapped[int] = mapped_column(
        ForeignKey("incident_resolutions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    after_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
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
