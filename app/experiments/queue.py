"""PostgreSQL-backed очередь и выполнение прогонов экспериментов."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.contracts import ChatMessage
from app.ai.errors import ProviderNotConfiguredError, UnknownProviderError
from app.ai.models import Experiment, ExperimentRun, LLMCall, PromptVersion
from app.ai.providers import build_provider
from app.ai.providers.base import LLMProvider
from app.ai.service import execute_call
from app.core.config import Settings, settings
from app.experiments.evaluation import create_evaluation

logger = structlog.get_logger(__name__)

ProviderFactory = Callable[..., LLMProvider]
SessionFactory = Callable[[], Session]
RETRYABLE_ERROR_TYPES = frozenset({"provider_error", "timeout", "rate_limit"})


@dataclass(frozen=True)
class ClaimedRun:
    """Право worker-а выполнить одну конкретную попытку."""

    run_id: int
    worker_id: str
    lease_token: UUID
    attempt: int


@dataclass(frozen=True)
class RunInput:
    """Все входные данные вызова, загруженные до обращения к LLM."""

    provider: str
    model: str
    prompt_version: str
    messages: list[ChatMessage]
    criteria: dict[str, object]
    temperature: float
    max_tokens: int | None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _database_now(db: Session) -> datetime:
    value = db.scalar(select(func.now()))
    if not isinstance(value, datetime):
        raise RuntimeError("База данных не вернула текущее время")
    return _utc(value)


def _clear_lease(run: ExperimentRun) -> None:
    run.worker_id = None
    run.lease_token = None
    run.lease_expires_at = None


def claim_next_run(
    db: Session,
    worker_id: str,
    *,
    lease_seconds: int,
) -> ClaimedRun | None:
    """Атомарно захватывает один готовый прогон через SKIP LOCKED."""
    run = db.scalar(
        select(ExperimentRun)
        .where(
            ExperimentRun.status == "pending",
            ExperimentRun.attempt_count < ExperimentRun.max_attempts,
            or_(
                ExperimentRun.next_retry_at.is_(None),
                ExperimentRun.next_retry_at <= func.now(),
            ),
        )
        .order_by(
            func.coalesce(
                ExperimentRun.next_retry_at,
                ExperimentRun.created_at,
            ),
            ExperimentRun.id,
        )
        .with_for_update(skip_locked=True)
        .limit(1),
    )
    if run is None:
        db.rollback()
        return None

    now = _database_now(db)
    token = uuid4()
    run.status = "running"
    run.worker_id = worker_id
    run.lease_token = token
    run.lease_expires_at = now + timedelta(seconds=lease_seconds)
    run.attempt_count += 1
    run.started_at = run.started_at or now
    run.finished_at = None
    run.next_retry_at = None
    run.error = None
    db.commit()

    logger.info(
        "experiment_run_claimed",
        experiment_run_id=run.id,
        worker_id=worker_id,
        attempt=run.attempt_count,
    )
    return ClaimedRun(
        run_id=run.id,
        worker_id=worker_id,
        lease_token=token,
        attempt=run.attempt_count,
    )


def recover_expired_runs(db: Session) -> int:
    """Возвращает истёкшие lease в очередь либо завершает их ошибкой."""
    runs = list(
        db.scalars(
            select(ExperimentRun)
            .where(
                ExperimentRun.status == "running",
                ExperimentRun.lease_expires_at <= func.now(),
            )
            .order_by(ExperimentRun.id)
            .with_for_update(skip_locked=True),
        ),
    )
    if not runs:
        db.rollback()
        return 0

    now = _database_now(db)
    for run in runs:
        _clear_lease(run)
        run.error = "Истёк lease worker-а"
        if run.attempt_count >= run.max_attempts:
            run.status = "failed"
            run.finished_at = now
            run.next_retry_at = None
        else:
            run.status = "pending"
            run.finished_at = None
            run.next_retry_at = now
    db.commit()
    logger.warning("experiment_leases_recovered", count=len(runs))
    return len(runs)


def _load_run_input(db: Session, claim: ClaimedRun) -> RunInput | None:
    run = db.scalar(
        select(ExperimentRun).where(
            ExperimentRun.id == claim.run_id,
            ExperimentRun.status == "running",
            ExperimentRun.worker_id == claim.worker_id,
            ExperimentRun.lease_token == claim.lease_token,
            ExperimentRun.lease_expires_at > func.now(),
        ),
    )
    if run is None:
        return None
    experiment = db.get(Experiment, run.experiment_id)
    if experiment is None:
        raise RuntimeError("Эксперимент для прогона не найден")
    prompt = db.get(PromptVersion, experiment.prompt_version_id)
    if prompt is None:
        raise RuntimeError("Версия промпта для эксперимента не найдена")

    max_tokens_value = run.parameters.get("max_tokens")
    return RunInput(
        provider=run.provider,
        model=run.model,
        prompt_version=prompt.version,
        messages=[
            ChatMessage(role="system", content=prompt.content),
            ChatMessage(
                role="user",
                content=json.dumps(
                    experiment.scenario,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        ],
        criteria=dict(experiment.criteria),
        temperature=float(run.parameters.get("temperature", 0.0)),
        max_tokens=(int(max_tokens_value) if max_tokens_value is not None else None),
    )


def _owned_run(db: Session, claim: ClaimedRun) -> ExperimentRun | None:
    return db.scalar(
        select(ExperimentRun)
        .where(
            ExperimentRun.id == claim.run_id,
            ExperimentRun.status == "running",
            ExperimentRun.worker_id == claim.worker_id,
            ExperimentRun.lease_token == claim.lease_token,
            ExperimentRun.lease_expires_at > func.now(),
        )
        .with_for_update(),
    )


def _finalize_success(
    db: Session,
    claim: ClaimedRun,
    call_id: int,
    criteria: dict[str, object],
) -> bool:
    run = _owned_run(db, claim)
    if run is None:
        db.rollback()
        return False
    call = db.get(LLMCall, call_id)
    if (
        call is None
        or call.status != "success"
        or call.experiment_run_id != run.id
        or call.experiment_attempt != claim.attempt
        or call.lease_token != claim.lease_token
    ):
        db.rollback()
        raise RuntimeError("LLM-вызов не принадлежит актуальной попытке")

    now = _database_now(db)
    create_evaluation(db, call, criteria)
    run.final_call_id = call.id
    run.status = "completed"
    run.error = None
    run.finished_at = now
    run.next_retry_at = None
    _clear_lease(run)
    db.commit()
    logger.info(
        "experiment_run_completed",
        experiment_run_id=run.id,
        attempt=claim.attempt,
        final_call_id=call.id,
    )
    return True


def _finalize_failure(
    db: Session,
    claim: ClaimedRun,
    *,
    message: str,
    retryable: bool,
    retry_base_seconds: int,
    call_id: int | None = None,
) -> bool:
    run = _owned_run(db, claim)
    if run is None:
        db.rollback()
        return False
    call = db.get(LLMCall, call_id) if call_id is not None else None
    if call is not None and (
        call.experiment_run_id != run.id
        or call.experiment_attempt != claim.attempt
        or call.lease_token != claim.lease_token
    ):
        db.rollback()
        raise RuntimeError("LLM-вызов не принадлежит актуальной попытке")

    now = _database_now(db)
    run.error = message
    _clear_lease(run)
    if retryable and run.attempt_count < run.max_attempts:
        delay = retry_base_seconds * (2 ** (run.attempt_count - 1))
        run.status = "pending"
        run.next_retry_at = now + timedelta(seconds=delay)
        run.finished_at = None
        event = "experiment_run_retry_scheduled"
    else:
        run.status = "failed"
        run.final_call_id = call.id if call is not None else None
        run.next_retry_at = None
        run.finished_at = now
        event = "experiment_run_failed"
    db.commit()
    logger.warning(
        event,
        experiment_run_id=run.id,
        attempt=claim.attempt,
        error=message,
    )
    return True


def execute_claimed_run(
    session_factory: SessionFactory,
    claim: ClaimedRun,
    *,
    provider_factory: ProviderFactory = build_provider,
    provider_settings: Settings = settings,
) -> bool:
    """Выполняет LLM-вызов вне транзакции и фиксирует только свой lease."""
    try:
        with session_factory() as db:
            run_input = _load_run_input(db, claim)
    except Exception as exc:
        with session_factory() as db:
            return _finalize_failure(
                db,
                claim,
                message=str(exc),
                retryable=False,
                retry_base_seconds=provider_settings.experiment_retry_base_seconds,
            )
    if run_input is None:
        return False

    provider: LLMProvider | None = None
    try:
        provider = provider_factory(
            run_input.provider,
            provider_settings,
            model=run_input.model,
        )
        with session_factory() as db:
            call = execute_call(
                db,
                provider,
                run_input.messages,
                temperature=run_input.temperature,
                max_tokens=run_input.max_tokens,
                prompt_version=run_input.prompt_version,
                experiment_run_id=claim.run_id,
                experiment_attempt=claim.attempt,
                lease_token=claim.lease_token,
            )
        if call.status == "success":
            with session_factory() as db:
                return _finalize_success(
                    db,
                    claim,
                    call.id,
                    run_input.criteria,
                )
        with session_factory() as db:
            return _finalize_failure(
                db,
                claim,
                message=call.error_message or "Ошибка LLM-провайдера",
                retryable=call.error_type in RETRYABLE_ERROR_TYPES,
                retry_base_seconds=provider_settings.experiment_retry_base_seconds,
                call_id=call.id,
            )
    except (ProviderNotConfiguredError, UnknownProviderError, ValueError) as exc:
        with session_factory() as db:
            return _finalize_failure(
                db,
                claim,
                message=str(exc),
                retryable=False,
                retry_base_seconds=provider_settings.experiment_retry_base_seconds,
            )
    except Exception as exc:
        logger.exception(
            "experiment_attempt_unexpected_error",
            experiment_run_id=claim.run_id,
            attempt=claim.attempt,
        )
        with session_factory() as db:
            return _finalize_failure(
                db,
                claim,
                message=str(exc),
                retryable=True,
                retry_base_seconds=provider_settings.experiment_retry_base_seconds,
            )
    finally:
        if provider is not None:
            try:
                provider.close()
            except Exception:
                logger.exception(
                    "experiment_provider_close_failed",
                    experiment_run_id=claim.run_id,
                )


def process_next_run(
    session_factory: SessionFactory,
    worker_id: str,
    *,
    provider_factory: ProviderFactory = build_provider,
    provider_settings: Settings = settings,
) -> bool:
    """Захватывает и выполняет один прогон; False означает пустую очередь."""
    with session_factory() as db:
        claim = claim_next_run(
            db,
            worker_id,
            lease_seconds=provider_settings.experiment_worker_lease_seconds,
        )
    if claim is None:
        return False
    execute_claimed_run(
        session_factory,
        claim,
        provider_factory=provider_factory,
        provider_settings=provider_settings,
    )
    return True
