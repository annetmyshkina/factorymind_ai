from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    String,
    Text,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import UTCDateTime
from app.monitoring.metrics import METRICS

_METRIC_NAMES_SQL = ", ".join(f"'{name}'" for name in METRICS)


class MonitoringRule(Base):
    """Правило проверки показаний оборудования."""

    __tablename__ = "monitoring_rules"
    __table_args__ = (
        CheckConstraint(
            "operator IN ('gt', 'lt')",
            name="ck_monitoring_rules_operator",
        ),
        CheckConstraint(
            f"metric_name IN ({_METRIC_NAMES_SQL})",
            name="ck_monitoring_rules_metric_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class EquipmentDeviation(Base):
    """Зафиксированное отклонение показаний оборудования."""

    __tablename__ = "equipment_deviations"
    __table_args__ = (
        CheckConstraint(
            f"metric_name IN ({_METRIC_NAMES_SQL})",
            name="ck_equipment_deviations_metric_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    telemetry_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipment_telemetry.id", ondelete="SET NULL"),
        nullable=True,
    )

    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitoring_rules.id", ondelete="SET NULL"),
        nullable=True,
    )

    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)

    message: Mapped[str] = mapped_column(Text, nullable=False)

    detected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    is_resolved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
