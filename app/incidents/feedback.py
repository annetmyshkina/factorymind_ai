"""Обратная связь инженера и аудит подтверждённых результатов диагностики."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.incidents.experience import build_resolution_search_text
from app.incidents.models import (
    Incident,
    IncidentAnalysis,
    IncidentAnalysisFeedback,
    IncidentResolution,
    IncidentResolutionEvent,
)
from app.incidents.schemas import (
    IncidentAnalysisFeedbackCreate,
    IncidentResolutionCreate,
    IncidentResolutionUpdate,
)


class FeedbackIncidentNotFoundError(LookupError):
    """Инцидент не найден."""


class FeedbackAnalysisNotFoundError(LookupError):
    """Анализ не найден или относится к другому инциденту."""


class IncidentResolutionNotFoundError(LookupError):
    """Подтверждённый результат инцидента не найден."""


class IncidentResolutionConflictError(ValueError):
    """Операция противоречит текущему состоянию результата или инцидента."""


def _effective_actor(authenticated_actor: str | None, legacy_actor: str | None) -> str:
    actor = authenticated_actor or legacy_actor
    if actor is None:
        raise ValueError("Автор операции не определён")
    return actor


def _get_incident(
    db: Session,
    incident_id: int,
    *,
    for_update: bool = False,
) -> Incident:
    statement = select(Incident).where(Incident.id == incident_id)
    if for_update:
        statement = statement.with_for_update()
    incident = db.scalar(statement)
    if incident is None:
        db.rollback()
        raise FeedbackIncidentNotFoundError
    return incident


def _get_analysis_for_incident(
    db: Session,
    incident_id: int,
    analysis_id: int,
) -> IncidentAnalysis:
    analysis = db.scalar(
        select(IncidentAnalysis).where(
            IncidentAnalysis.id == analysis_id,
            IncidentAnalysis.incident_id == incident_id,
        ),
    )
    if analysis is None:
        db.rollback()
        raise FeedbackAnalysisNotFoundError
    return analysis


def add_analysis_feedback(
    db: Session,
    *,
    incident_id: int,
    analysis_id: int,
    payload: IncidentAnalysisFeedbackCreate,
    actor: str | None = None,
    actor_verified: bool = False,
) -> IncidentAnalysisFeedback:
    """Добавляет неизменяемую оценку, не превращая её в подтверждённый факт."""
    _get_incident(db, incident_id)
    _get_analysis_for_incident(db, incident_id, analysis_id)
    feedback = IncidentAnalysisFeedback(
        analysis_id=analysis_id,
        rating=payload.rating,
        comment=payload.comment,
        actor=_effective_actor(actor, payload.actor),
        actor_verified=actor_verified,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def list_analysis_feedback(
    db: Session,
    *,
    incident_id: int,
    analysis_id: int,
    limit: int,
    offset: int,
) -> list[IncidentAnalysisFeedback]:
    """Возвращает оценки анализа в порядке добавления."""
    _get_incident(db, incident_id)
    _get_analysis_for_incident(db, incident_id, analysis_id)
    return list(
        db.scalars(
            select(IncidentAnalysisFeedback)
            .where(IncidentAnalysisFeedback.analysis_id == analysis_id)
            .order_by(
                IncidentAnalysisFeedback.created_at,
                IncidentAnalysisFeedback.id,
            )
            .offset(offset)
            .limit(limit),
        ),
    )


def _resolution_snapshot(resolution: IncidentResolution) -> dict[str, object]:
    return {
        "id": resolution.id,
        "incident_id": resolution.incident_id,
        "analysis_id": resolution.analysis_id,
        "checks_performed": list(resolution.checks_performed),
        "confirmed_cause": resolution.confirmed_cause,
        "actions_taken": list(resolution.actions_taken),
        "outcome": resolution.outcome,
        "actor": resolution.actor,
        "actor_verified": resolution.actor_verified,
        "is_active": resolution.is_active,
        "revision": resolution.revision,
        "confirmed_at": resolution.confirmed_at.isoformat(),
        "updated_at": resolution.updated_at.isoformat(),
        "revoked_at": (
            resolution.revoked_at.isoformat()
            if resolution.revoked_at is not None
            else None
        ),
    }


def _refresh_resolution_search_text(resolution: IncidentResolution) -> None:
    resolution.search_text = build_resolution_search_text(
        checks_performed=list(resolution.checks_performed),
        confirmed_cause=resolution.confirmed_cause,
        actions_taken=list(resolution.actions_taken),
        outcome=resolution.outcome,
    )


def _add_resolution_event(
    db: Session,
    resolution: IncidentResolution,
    *,
    event_type: str,
    actor: str,
    actor_verified: bool,
    reason: str | None,
    before_snapshot: dict[str, object] | None,
) -> None:
    db.add(
        IncidentResolutionEvent(
            resolution_id=resolution.id,
            event_type=event_type,
            actor=actor,
            actor_verified=actor_verified,
            reason=reason,
            before_snapshot=before_snapshot,
            after_snapshot=_resolution_snapshot(resolution),
        ),
    )


def _get_resolution_for_update(
    db: Session,
    incident_id: int,
) -> IncidentResolution | None:
    return db.scalar(
        select(IncidentResolution)
        .where(IncidentResolution.incident_id == incident_id)
        .with_for_update(),
    )


def confirm_incident_resolution(
    db: Session,
    *,
    incident_id: int,
    payload: IncidentResolutionCreate,
    actor: str | None = None,
    actor_verified: bool = False,
) -> IncidentResolution:
    """Подтверждает результат либо повторно активирует отозванный результат."""
    incident = _get_incident(db, incident_id, for_update=True)
    if incident.status not in {"resolved", "closed"}:
        db.rollback()
        raise IncidentResolutionConflictError(
            "Подтвердить результат можно только для resolved или closed инцидента",
        )
    if payload.analysis_id is not None:
        _get_analysis_for_incident(db, incident_id, payload.analysis_id)

    resolution = _get_resolution_for_update(db, incident_id)
    if resolution is not None and resolution.is_active:
        db.rollback()
        raise IncidentResolutionConflictError(
            "У инцидента уже есть активный подтверждённый результат",
        )
    if resolution is not None and payload.reason is None:
        db.rollback()
        raise IncidentResolutionConflictError(
            "Повторное подтверждение требует указать причину",
        )

    now = datetime.now(UTC)
    before_snapshot = (
        _resolution_snapshot(resolution) if resolution is not None else None
    )
    if resolution is None:
        resolution = IncidentResolution(
            incident_id=incident_id,
            revision=1,
            confirmed_at=now,
            updated_at=now,
        )
        db.add(resolution)
    else:
        resolution.revision += 1
        resolution.confirmed_at = now
        resolution.updated_at = now

    resolution.analysis_id = payload.analysis_id
    resolution.checks_performed = list(payload.checks_performed)
    resolution.confirmed_cause = payload.confirmed_cause
    resolution.actions_taken = list(payload.actions_taken)
    resolution.outcome = payload.outcome
    effective_actor = _effective_actor(actor, payload.actor)
    resolution.actor = effective_actor
    resolution.actor_verified = actor_verified
    resolution.is_active = True
    resolution.revoked_at = None
    _refresh_resolution_search_text(resolution)
    db.flush()
    _add_resolution_event(
        db,
        resolution,
        event_type="confirmed",
        actor=effective_actor,
        actor_verified=actor_verified,
        reason=payload.reason,
        before_snapshot=before_snapshot,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise IncidentResolutionConflictError(
            "Результат инцидента был изменён параллельной операцией",
        ) from None
    db.refresh(resolution)
    return resolution


def get_incident_resolution(
    db: Session,
    incident_id: int,
) -> IncidentResolution:
    """Возвращает текущий снимок, включая отозванное состояние."""
    _get_incident(db, incident_id)
    resolution = db.scalar(
        select(IncidentResolution).where(
            IncidentResolution.incident_id == incident_id,
        ),
    )
    if resolution is None:
        raise IncidentResolutionNotFoundError
    return resolution


def correct_incident_resolution(
    db: Session,
    *,
    incident_id: int,
    payload: IncidentResolutionUpdate,
    actor: str | None = None,
    actor_verified: bool = False,
) -> IncidentResolution:
    """Исправляет активный результат и атомарно сохраняет снимки аудита."""
    _get_incident(db, incident_id)
    resolution = _get_resolution_for_update(db, incident_id)
    if resolution is None:
        db.rollback()
        raise IncidentResolutionNotFoundError
    if not resolution.is_active:
        db.rollback()
        raise IncidentResolutionConflictError(
            "Отозванный результат нужно подтвердить заново, а не исправлять",
        )
    if "analysis_id" in payload.model_fields_set and payload.analysis_id is not None:
        _get_analysis_for_incident(db, incident_id, payload.analysis_id)

    before_snapshot = _resolution_snapshot(resolution)
    before_values = (
        resolution.analysis_id,
        tuple(resolution.checks_performed),
        resolution.confirmed_cause,
        tuple(resolution.actions_taken),
        resolution.outcome,
    )
    if "analysis_id" in payload.model_fields_set:
        resolution.analysis_id = payload.analysis_id
    if payload.checks_performed is not None:
        resolution.checks_performed = list(payload.checks_performed)
    if "confirmed_cause" in payload.model_fields_set:
        resolution.confirmed_cause = payload.confirmed_cause
    if payload.actions_taken is not None:
        resolution.actions_taken = list(payload.actions_taken)
    if payload.outcome is not None:
        resolution.outcome = payload.outcome

    after_values = (
        resolution.analysis_id,
        tuple(resolution.checks_performed),
        resolution.confirmed_cause,
        tuple(resolution.actions_taken),
        resolution.outcome,
    )
    if before_values == after_values:
        db.rollback()
        raise IncidentResolutionConflictError("Изменения результата отсутствуют")

    resolution.revision += 1
    effective_actor = _effective_actor(actor, payload.actor)
    resolution.actor = effective_actor
    resolution.actor_verified = actor_verified
    resolution.updated_at = datetime.now(UTC)
    _refresh_resolution_search_text(resolution)
    db.flush()
    _add_resolution_event(
        db,
        resolution,
        event_type="corrected",
        actor=effective_actor,
        actor_verified=actor_verified,
        reason=payload.reason,
        before_snapshot=before_snapshot,
    )
    db.commit()
    db.refresh(resolution)
    return resolution


def revoke_incident_resolution(
    db: Session,
    *,
    incident_id: int,
    actor: str,
    reason: str,
    actor_verified: bool = False,
) -> IncidentResolution:
    """Отзывает активный результат, сохраняя его данные и полный аудит."""
    _get_incident(db, incident_id)
    resolution = _get_resolution_for_update(db, incident_id)
    if resolution is None:
        db.rollback()
        raise IncidentResolutionNotFoundError
    if not resolution.is_active:
        db.rollback()
        raise IncidentResolutionConflictError("Результат уже отозван")

    before_snapshot = _resolution_snapshot(resolution)
    now = datetime.now(UTC)
    resolution.is_active = False
    resolution.revision += 1
    resolution.updated_at = now
    resolution.revoked_at = now
    db.flush()
    _add_resolution_event(
        db,
        resolution,
        event_type="revoked",
        actor=actor,
        actor_verified=actor_verified,
        reason=reason,
        before_snapshot=before_snapshot,
    )
    db.commit()
    db.refresh(resolution)
    return resolution


def revoke_resolution_on_incident_reopen(
    db: Session,
    *,
    incident_id: int,
    actor: str = "system",
    actor_verified: bool = False,
) -> None:
    """Не оставляет подтверждённое решение активным после возврата в работу."""
    resolution = _get_resolution_for_update(db, incident_id)
    if resolution is None or not resolution.is_active:
        return
    before_snapshot = _resolution_snapshot(resolution)
    now = datetime.now(UTC)
    resolution.is_active = False
    resolution.revision += 1
    resolution.updated_at = now
    resolution.revoked_at = now
    db.flush()
    _add_resolution_event(
        db,
        resolution,
        event_type="revoked",
        actor=actor,
        actor_verified=actor_verified,
        reason="Инцидент возвращён в активный статус",
        before_snapshot=before_snapshot,
    )


def list_resolution_events(
    db: Session,
    *,
    incident_id: int,
) -> list[IncidentResolutionEvent]:
    """Возвращает неизменяемую историю результата диагностики."""
    resolution = get_incident_resolution(db, incident_id)
    return list(
        db.scalars(
            select(IncidentResolutionEvent)
            .where(IncidentResolutionEvent.resolution_id == resolution.id)
            .order_by(
                IncidentResolutionEvent.created_at,
                IncidentResolutionEvent.id,
            ),
        ),
    )
