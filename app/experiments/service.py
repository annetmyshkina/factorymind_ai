"""Создание, выполнение и чтение экспериментов."""

import json
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.contracts import ChatMessage
from app.ai.models import (
    Evaluation,
    EvaluationResult,
    Experiment,
    ExperimentRun,
    LLMCall,
    PromptVersion,
)
from app.ai.providers import build_provider
from app.ai.providers.base import LLMProvider
from app.ai.schemas import (
    EvaluationResponse,
    EvaluationResultResponse,
    ExperimentCreate,
    ExperimentDetailResponse,
    ExperimentReportResponse,
    ExperimentReportRun,
    ExperimentResponse,
    ExperimentRunDetailResponse,
    ExperimentRunResponse,
    LLMCallResponse,
)
from app.ai.service import execute_call
from app.core.config import Settings, settings
from app.core.database import SessionLocal
from app.experiments.evaluation import create_evaluation

logger = structlog.get_logger(__name__)

ProviderFactory = Callable[..., LLMProvider]


class PromptVersionNotFoundError(LookupError):
    """Указанная версия промпта не существует."""


class ExperimentConflictError(ValueError):
    """Эксперимент нарушает ограничение уникальности."""


def create_experiment(db: Session, payload: ExperimentCreate) -> Experiment:
    """Атомарно создаёт эксперимент и все запрошенные прогоны."""
    if db.get(PromptVersion, payload.prompt_version_id) is None:
        raise PromptVersionNotFoundError

    experiment = Experiment(
        name=payload.name,
        description=payload.description,
        prompt_version_id=payload.prompt_version_id,
        scenario=payload.scenario,
        criteria={
            name: criterion.model_dump(mode="json")
            for name, criterion in payload.criteria.items()
        },
    )
    db.add(experiment)
    db.flush()

    for requested_run in payload.runs:
        db.add(
            ExperimentRun(
                experiment_id=experiment.id,
                provider=requested_run.provider,
                model=requested_run.model,
                parameters=requested_run.parameters.model_dump(mode="json"),
            ),
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ExperimentConflictError from None

    db.refresh(experiment)
    return experiment


def _evaluation_response(
    evaluation: Evaluation,
    results: list[EvaluationResult],
) -> EvaluationResponse:
    return EvaluationResponse(
        id=evaluation.id,
        llm_call_id=evaluation.llm_call_id,
        evaluator=evaluation.evaluator,
        summary=evaluation.summary,
        results=[EvaluationResultResponse.model_validate(item) for item in results],
        created_at=evaluation.created_at,
    )


def get_experiment_detail(
    db: Session,
    experiment: Experiment,
) -> ExperimentDetailResponse:
    """Собирает эксперимент, вызовы и оценки без ленивых ORM-связей."""
    runs = list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.experiment_id == experiment.id)
            .order_by(ExperimentRun.id),
        ),
    )
    run_ids = [run.id for run in runs]
    calls: dict[int, LLMCall] = {}
    if run_ids:
        for call in db.scalars(
            select(LLMCall)
            .where(LLMCall.experiment_run_id.in_(run_ids))
            .order_by(LLMCall.id.desc()),
        ):
            if call.experiment_run_id is not None:
                calls.setdefault(call.experiment_run_id, call)

    call_ids = [call.id for call in calls.values()]
    evaluations: dict[int, Evaluation] = {}
    if call_ids:
        evaluations = {
            item.llm_call_id: item
            for item in db.scalars(
                select(Evaluation).where(Evaluation.llm_call_id.in_(call_ids)),
            )
        }

    evaluation_ids = [item.id for item in evaluations.values()]
    results_by_evaluation: dict[int, list[EvaluationResult]] = {
        evaluation_id: [] for evaluation_id in evaluation_ids
    }
    if evaluation_ids:
        for result in db.scalars(
            select(EvaluationResult)
            .where(EvaluationResult.evaluation_id.in_(evaluation_ids))
            .order_by(EvaluationResult.criterion),
        ):
            results_by_evaluation[result.evaluation_id].append(result)

    run_responses: list[ExperimentRunDetailResponse] = []
    for run in runs:
        call = calls.get(run.id)
        evaluation = evaluations.get(call.id) if call is not None else None
        run_data = ExperimentRunResponse.model_validate(run).model_dump()
        run_responses.append(
            ExperimentRunDetailResponse(
                **run_data,
                call=LLMCallResponse.model_validate(call) if call else None,
                evaluation=(
                    _evaluation_response(
                        evaluation,
                        results_by_evaluation[evaluation.id],
                    )
                    if evaluation
                    else None
                ),
            ),
        )

    experiment_data = ExperimentResponse.model_validate(experiment).model_dump()
    return ExperimentDetailResponse(**experiment_data, runs=run_responses)


def get_experiment_report(
    db: Session,
    experiment: Experiment,
) -> ExperimentReportResponse:
    """Строит сравнительный отчёт, сохраняя оценки по критериям раздельно."""
    detail = get_experiment_detail(db, experiment)
    counts = {status: 0 for status in ("pending", "running", "succeeded", "failed")}
    report_runs: list[ExperimentReportRun] = []

    for run in detail.runs:
        counts[run.status] += 1
        report_runs.append(
            ExperimentReportRun(
                provider=run.provider,
                model=run.model,
                actual_model=run.call.model if run.call else None,
                status=run.status,
                error=run.error,
                response_text=run.call.response_text if run.call else None,
                latency_ms=run.call.latency_ms if run.call else None,
                prompt_tokens=run.call.prompt_tokens if run.call else None,
                completion_tokens=(run.call.completion_tokens if run.call else None),
                evaluation=run.evaluation,
            ),
        )

    return ExperimentReportResponse(
        experiment_id=experiment.id,
        name=experiment.name,
        prompt_version_id=experiment.prompt_version_id,
        run_counts=counts,
        runs=report_runs,
    )


def _fail_run(db: Session, run_id: int, error: Exception) -> None:
    db.rollback()
    run = db.get(ExperimentRun, run_id)
    if run is None:
        return
    run.status = "failed"
    run.error = str(error)
    run.finished_at = datetime.now(UTC)
    db.commit()
    logger.warning(
        "experiment_run_failed",
        experiment_run_id=run_id,
        error_type=type(error).__name__,
    )


def _execute_run(
    db: Session,
    experiment: Experiment,
    prompt: PromptVersion,
    run: ExperimentRun,
    *,
    provider_factory: ProviderFactory,
    provider_settings: Settings,
) -> None:
    run_id = run.id
    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.error = None
    db.commit()

    provider: LLMProvider | None = None
    try:
        provider = provider_factory(
            run.provider,
            provider_settings,
            model=run.model,
        )
        messages = [
            ChatMessage(role="system", content=prompt.content),
            ChatMessage(
                role="user",
                content=json.dumps(
                    experiment.scenario,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        ]
        max_tokens_value = run.parameters.get("max_tokens")
        call = execute_call(
            db,
            provider,
            messages,
            temperature=float(run.parameters.get("temperature", 0.0)),
            max_tokens=(
                int(max_tokens_value) if max_tokens_value is not None else None
            ),
            prompt_version=prompt.version,
            experiment_run_id=run.id,
        )

        if call.status == "error":
            run.status = "failed"
            run.error = call.error_message
        else:
            create_evaluation(db, call, experiment.criteria)
            run.status = "succeeded"
            run.error = None
        run.finished_at = datetime.now(UTC)
        db.commit()
        logger.info(
            "experiment_run_finished",
            experiment_run_id=run.id,
            status=run.status,
        )
    except Exception as exc:
        _fail_run(db, run_id, exc)
    finally:
        if provider is not None:
            try:
                provider.close()
            except Exception:
                logger.exception(
                    "experiment_provider_close_failed",
                    experiment_run_id=run_id,
                )


def execute_experiment(
    db: Session,
    experiment_id: int,
    *,
    provider_factory: ProviderFactory = build_provider,
    provider_settings: Settings = settings,
) -> None:
    """Выполняет ожидающие прогоны независимо, сохраняя частичные результаты."""
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        logger.warning("experiment_not_found", experiment_id=experiment_id)
        return
    prompt = db.get(PromptVersion, experiment.prompt_version_id)
    if prompt is None:
        logger.error("experiment_prompt_missing", experiment_id=experiment_id)
        return

    runs = list(
        db.scalars(
            select(ExperimentRun)
            .where(
                ExperimentRun.experiment_id == experiment_id,
                ExperimentRun.status == "pending",
            )
            .order_by(ExperimentRun.id),
        ),
    )
    for run in runs:
        _execute_run(
            db,
            experiment,
            prompt,
            run,
            provider_factory=provider_factory,
            provider_settings=provider_settings,
        )


def run_experiment_in_background(experiment_id: int) -> None:
    """Точка входа фоновой задачи этапа 4; durable worker относится к этапу 5."""
    with SessionLocal() as db:
        execute_experiment(db, experiment_id)
