"""Модели AI: журнал вызовов, версии промптов, эксперименты."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
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

    # FK на прогон эксперимента (nullable: обычные вызовы без эксперимента)
    experiment_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("experiment_runs.id", ondelete="SET NULL"),
        index=True,
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


class Experiment(Base):
    """Эксперимент: сценарий на неизменяемой версии промпта."""

    __tablename__ = "experiments"
    __table_args__ = (Index("ix_experiments_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    prompt_version_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    # JSON: входные данные сценария (температура, пороги и т.д.)
    scenario: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    # JSON: критерии оценки (correctness, groundedness, ...)
    criteria: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class ExperimentRun(Base):
    """Один прогон эксперимента на конкретной модели."""

    __tablename__ = "experiment_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_experiment_runs_status",
        ),
        UniqueConstraint(
            "experiment_id",
            "provider",
            "model",
            name="uq_experiment_runs_exp_provider_model",
        ),
        Index("ix_experiment_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    # JSON: параметры генерации (temperature, max_tokens, seed, ...)
    parameters: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class Evaluation(Base):
    """Детерминированная оценка одного сохранённого LLM-вызова."""

    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint(
            "llm_call_id",
            name="uq_evaluations_llm_call_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    llm_call_id: Mapped[int] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    evaluator: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class EvaluationResult(Base):
    """Результат оценки по одному независимому критерию."""

    __tablename__ = "evaluation_results"
    __table_args__ = (
        CheckConstraint(
            "score >= 0 AND score <= 2",
            name="ck_evaluation_results_score",
        ),
        UniqueConstraint(
            "evaluation_id",
            "criterion",
            name="uq_evaluation_results_evaluation_criterion",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    criterion: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
