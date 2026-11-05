"""API экспериментов, результатов и сравнительных отчётов."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.models import Experiment
from app.ai.schemas import (
    ExperimentCreate,
    ExperimentDetailResponse,
    ExperimentReportResponse,
)
from app.core.database import get_db
from app.experiments.service import (
    ExperimentConflictError,
    PromptVersionNotFoundError,
    create_experiment,
    get_experiment_detail,
    get_experiment_report,
    run_experiment_in_background,
)

router = APIRouter(prefix="/experiments", tags=["Experiments"])


@router.post(
    "",
    response_model=ExperimentDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_experiment_endpoint(
    payload: ExperimentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ExperimentDetailResponse:
    """Атомарно создаёт эксперимент и запускает его после отправки ответа."""
    try:
        experiment = create_experiment(db, payload)
    except PromptVersionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Версия промпта не найдена",
        ) from None
    except ExperimentConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Конфликт прогонов эксперимента",
        ) from None

    response = get_experiment_detail(db, experiment)
    background_tasks.add_task(run_experiment_in_background, experiment.id)
    return response


@router.get(
    "/{experiment_id}/report",
    response_model=ExperimentReportResponse,
)
def experiment_report_endpoint(
    experiment_id: int,
    db: Session = Depends(get_db),
) -> ExperimentReportResponse:
    """Возвращает сравнительный отчёт с независимыми оценками."""
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Эксперимент не найден",
        )
    return get_experiment_report(db, experiment)


@router.get(
    "/{experiment_id}",
    response_model=ExperimentDetailResponse,
)
def get_experiment_endpoint(
    experiment_id: int,
    db: Session = Depends(get_db),
) -> ExperimentDetailResponse:
    """Возвращает статус и результаты всех прогонов эксперимента."""
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Эксперимент не найден",
        )
    return get_experiment_detail(db, experiment)
