from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.equipment.models import Equipment
from app.incidents.models import Incident, IncidentEvent
from app.incidents.schemas import (
    IncidentCreate,
    IncidentDetailResponse,
    IncidentEventResponse,
    IncidentResponse,
    IncidentStatus,
    IncidentUpdate,
    LinkDeviationRequest,
)
from app.incidents.service import (
    DeviationNotFoundError,
    InvalidTransitionError,
    assign,
    change_status,
    create_incident,
    link_deviation,
)

router = APIRouter(prefix="/incidents", tags=["Incidents"])

logger = structlog.get_logger(__name__)


def _load_incident(
    db: Session,
    incident_id: int,
    *,
    with_relations: bool = False,
) -> Incident:
    """Загружает инцидент с equipment (и опционально deviations/events)."""
    query = (
        select(Incident)
        .where(Incident.id == incident_id)
        .options(joinedload(Incident.equipment))
    )
    if with_relations:
        query = query.options(
            selectinload(Incident.deviations),
            selectinload(Incident.events),
        )

    incident = db.scalar(query)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Инцидент не найден",
        )
    return incident


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
) -> IncidentResponse:
    """Создаёт инцидент для оборудования."""
    if db.get(Equipment, payload.equipment_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    incident = create_incident(
        db,
        equipment_id=payload.equipment_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        assigned_to=payload.assigned_to,
    )
    return _load_incident(db, incident.id)


@router.get("", response_model=list[IncidentResponse])
def list_incidents(
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    equipment_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[IncidentResponse]:
    """Возвращает инциденты с опциональными фильтрами."""
    query = (
        select(Incident)
        .options(joinedload(Incident.equipment))
        .order_by(Incident.created_at.desc())
    )
    if status_filter is not None:
        query = query.where(Incident.status == status_filter)
    if equipment_id is not None:
        query = query.where(Incident.equipment_id == equipment_id)

    return list(db.scalars(query).all())


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
) -> IncidentDetailResponse:
    """Инцидент + отклонения + история событий."""
    incident = _load_incident(db, incident_id, with_relations=True)

    return IncidentDetailResponse(
        **IncidentResponse.model_validate(incident).model_dump(),
        deviation_ids=[d.id for d in incident.deviations],
        events=[IncidentEventResponse.model_validate(e) for e in incident.events],
    )


@router.patch("/{incident_id}", response_model=IncidentResponse)
def update_incident(
    incident_id: int,
    payload: IncidentUpdate,
    db: Session = Depends(get_db),
) -> IncidentResponse:
    """Обновляет статус/исполнителя/severity."""
    incident = _load_incident(db, incident_id)

    if payload.severity is not None:
        incident.severity = payload.severity
        db.commit()

    if "description" in payload.model_fields_set:
        incident.description = payload.description
        db.commit()

    if "assigned_to" in payload.model_fields_set:
        assign(db, incident, payload.assigned_to)

    if payload.status is not None:
        try:
            change_status(db, incident, payload.status)
        except InvalidTransitionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    return _load_incident(db, incident_id)


@router.post(
    "/{incident_id}/deviations",
    status_code=status.HTTP_204_NO_CONTENT,
)
def add_deviation(
    incident_id: int,
    payload: LinkDeviationRequest,
    db: Session = Depends(get_db),
) -> None:
    """Привязывает отклонение к инциденту (идемпотентно)."""
    incident = _load_incident(db, incident_id)
    try:
        link_deviation(db, incident, payload.deviation_id)
    except DeviationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{incident_id}/events",
    response_model=list[IncidentEventResponse],
)
def list_events(
    incident_id: int,
    db: Session = Depends(get_db),
) -> list[IncidentEventResponse]:
    """История событий инцидента."""
    _load_incident(db, incident_id)  # 404 если нет
    events = db.scalars(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at),
    ).all()
    return list(events)
