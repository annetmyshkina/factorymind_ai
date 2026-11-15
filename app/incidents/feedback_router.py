"""API обратной связи инженера и подтверждённых результатов диагностики."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.incidents.feedback import (
    FeedbackAnalysisNotFoundError,
    FeedbackIncidentNotFoundError,
    IncidentResolutionConflictError,
    IncidentResolutionNotFoundError,
    add_analysis_feedback,
    confirm_incident_resolution,
    correct_incident_resolution,
    get_incident_resolution,
    list_analysis_feedback,
    list_resolution_events,
    revoke_incident_resolution,
)
from app.incidents.models import (
    IncidentAnalysisFeedback,
    IncidentResolution,
    IncidentResolutionEvent,
)
from app.incidents.schemas import (
    IncidentAnalysisFeedbackCreate,
    IncidentAnalysisFeedbackResponse,
    IncidentResolutionCreate,
    IncidentResolutionEventResponse,
    IncidentResolutionResponse,
    IncidentResolutionRevoke,
    IncidentResolutionUpdate,
)

router = APIRouter(prefix="/incidents", tags=["Engineer Feedback"])


def _raise_feedback_error(exc: Exception) -> None:
    if isinstance(exc, FeedbackIncidentNotFoundError):
        detail = "Инцидент не найден"
    else:
        detail = "Анализ не найден для этого инцидента"
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail,
    ) from exc


@router.post(
    "/{incident_id}/analyses/{analysis_id}/feedback",
    response_model=IncidentAnalysisFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_analysis_feedback(
    incident_id: int,
    analysis_id: int,
    payload: IncidentAnalysisFeedbackCreate,
    db: Session = Depends(get_db),
) -> IncidentAnalysisFeedback:
    """Добавляет оценку анализа без подтверждения его гипотез."""
    try:
        return add_analysis_feedback(
            db,
            incident_id=incident_id,
            analysis_id=analysis_id,
            payload=payload,
        )
    except (FeedbackIncidentNotFoundError, FeedbackAnalysisNotFoundError) as exc:
        _raise_feedback_error(exc)


@router.get(
    "/{incident_id}/analyses/{analysis_id}/feedback",
    response_model=list[IncidentAnalysisFeedbackResponse],
)
def get_analysis_feedback(
    incident_id: int,
    analysis_id: int,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[IncidentAnalysisFeedback]:
    """Возвращает неизменяемую историю субъективных оценок анализа."""
    try:
        return list_analysis_feedback(
            db,
            incident_id=incident_id,
            analysis_id=analysis_id,
            limit=limit,
            offset=offset,
        )
    except (FeedbackIncidentNotFoundError, FeedbackAnalysisNotFoundError) as exc:
        _raise_feedback_error(exc)


@router.post(
    "/{incident_id}/resolution",
    response_model=IncidentResolutionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_incident_resolution(
    incident_id: int,
    payload: IncidentResolutionCreate,
    db: Session = Depends(get_db),
) -> IncidentResolution:
    """Подтверждает результат завершённой диагностики."""
    try:
        return confirm_incident_resolution(
            db,
            incident_id=incident_id,
            payload=payload,
        )
    except FeedbackIncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Инцидент не найден",
        ) from exc
    except FeedbackAnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Анализ не найден для этого инцидента",
        ) from exc
    except IncidentResolutionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{incident_id}/resolution",
    response_model=IncidentResolutionResponse,
)
def read_incident_resolution(
    incident_id: int,
    db: Session = Depends(get_db),
) -> IncidentResolution:
    """Возвращает активный или отозванный текущий снимок результата."""
    try:
        return get_incident_resolution(db, incident_id)
    except FeedbackIncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Инцидент не найден",
        ) from exc
    except IncidentResolutionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Подтверждённый результат не найден",
        ) from exc


@router.patch(
    "/{incident_id}/resolution",
    response_model=IncidentResolutionResponse,
)
def update_incident_resolution(
    incident_id: int,
    payload: IncidentResolutionUpdate,
    db: Session = Depends(get_db),
) -> IncidentResolution:
    """Исправляет активный результат с обязательной записью аудита."""
    try:
        return correct_incident_resolution(
            db,
            incident_id=incident_id,
            payload=payload,
        )
    except FeedbackIncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Инцидент не найден",
        ) from exc
    except FeedbackAnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Анализ не найден для этого инцидента",
        ) from exc
    except IncidentResolutionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Подтверждённый результат не найден",
        ) from exc
    except IncidentResolutionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{incident_id}/resolution/revoke",
    response_model=IncidentResolutionResponse,
)
def revoke_resolution(
    incident_id: int,
    payload: IncidentResolutionRevoke,
    db: Session = Depends(get_db),
) -> IncidentResolution:
    """Отзывает подтверждение, не удаляя результат и историю."""
    try:
        return revoke_incident_resolution(
            db,
            incident_id=incident_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except FeedbackIncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Инцидент не найден",
        ) from exc
    except IncidentResolutionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Подтверждённый результат не найден",
        ) from exc
    except IncidentResolutionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{incident_id}/resolution/events",
    response_model=list[IncidentResolutionEventResponse],
)
def get_resolution_events(
    incident_id: int,
    db: Session = Depends(get_db),
) -> list[IncidentResolutionEvent]:
    """Возвращает полные снимки аудита подтверждённого результата."""
    try:
        return list_resolution_events(db, incident_id=incident_id)
    except FeedbackIncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Инцидент не найден",
        ) from exc
    except IncidentResolutionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Подтверждённый результат не найден",
        ) from exc
