from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import UTCDateTime


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    equipment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default=text("true"),
    )


class EquipmentAPIKey(Base):
    """Отзываемые машинные учётные данные одного оборудования."""

    __tablename__ = "equipment_api_keys"
    __table_args__ = (
        CheckConstraint(
            "(is_active AND revoked_at IS NULL) "
            "OR (NOT is_active AND revoked_at IS NOT NULL)",
            name="ck_equipment_api_keys_revocation_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )

    @property
    def key_prefix(self) -> str:
        return f"fmk_{self.key_id}"
