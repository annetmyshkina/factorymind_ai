"""Создание и чтение экспериментов."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.models import (
    Evaluation,
    EvaluationResult,
    Experiment,
    ExperimentRun,
    LLMCall,
    PromptVersion,
)
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
from app.core.config import settings


class PromptVersionNotFoundError(LookupError):
    """Указанная версия промпта не существует."""


class ExperimentConflictError(ValueError):
    """Эксперимент нарушает ограничение уникальности."""


def create_experiment(
    db: Session,
    payload: ExperimentCreate,
    *,
    max_attempts: int = settings.experiment_max_attempts,
) -> Experiment:
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
                max_attempts=max_attempts,
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
    calls_by_run: dict[int, list[LLMCall]] = {run_id: [] for run_id in run_ids}
    if run_ids:
        for call in db.scalars(
            select(LLMCall)
            .where(LLMCall.experiment_run_id.in_(run_ids))
            .order_by(LLMCall.id),
        ):
            if call.experiment_run_id is not None:
                calls_by_run[call.experiment_run_id].append(call)

    final_calls = {
        run.id: next(
            (call for call in calls_by_run[run.id] if call.id == run.final_call_id),
            None,
        )
        for run in runs
    }
    call_ids = [call.id for call in final_calls.values() if call is not None]
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
        call = final_calls[run.id]
        evaluation = evaluations.get(call.id) if call is not None else None
        run_data = ExperimentRunResponse.model_validate(run).model_dump()
        run_responses.append(
            ExperimentRunDetailResponse(
                **run_data,
                call=LLMCallResponse.model_validate(call) if call else None,
                attempts=[
                    LLMCallResponse.model_validate(item)
                    for item in calls_by_run[run.id]
                ],
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
    counts = {status: 0 for status in ("pending", "running", "completed", "failed")}
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
