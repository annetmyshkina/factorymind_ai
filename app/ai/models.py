"""Журнал вызовов LLM."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import UTCDateTime


class LLMCall(Base):
    """Сохранённый вызов языковой модели."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'error')",
            name="ck_llm_calls_status",
        ),
        Index("ix_llm_calls_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    request_messages: Mapped[list[dict[str, str]]] = mapped_column(
        JSON,
        nullable=False,
    )
    parameters: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )

    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    latency_ms: Mapped[int] = mapped_column(nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class PromptVersion(Base):
    """Неизменяемая версия промпта."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "name",
            "version",
            name="uq_prompt_versions_name_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
