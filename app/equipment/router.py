from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.equipment.models import Equipment
from app.equipment.schemas import (
    EquipmentCreate,
    EquipmentResponse,
    EquipmentUpdate,
)

router = APIRouter(
    prefix="/equipment",
    tags=["Equipment"],
)


@router.post(
    "",
    response_model=EquipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_equipment(
    equipment_data: EquipmentCreate,
    db: Session = Depends(get_db),
) -> Equipment:
    """Создаёт запись об оборудовании."""

    equipment = Equipment(**equipment_data.model_dump())

    db.add(equipment)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Оборудование с таким кодом уже существует",
        ) from exc

    db.refresh(equipment)

    return equipment


@router.get("", response_model=list[EquipmentResponse])
def list_equipment(
    db: Session = Depends(get_db),
) -> list[Equipment]:
    """Возвращает список зарегистрированного оборудования."""
    statement = select(Equipment).order_by(Equipment.id)
    result = db.scalars(statement).all()
    return list(result)


@router.get("/{equipment_id}", response_model=EquipmentResponse)
def get_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
) -> Equipment:
    """Возвращает оборудование по идентификатору."""
    equipment = db.get(Equipment, equipment_id)

    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    return equipment


@router.patch(
    "/{equipment_id}",
    response_model=EquipmentResponse,
)
def update_equipment(
    equipment_id: int,
    equipment_data: EquipmentUpdate,
    db: Session = Depends(get_db),
) -> Equipment:
    """Частично обновляет данные оборудования."""
    equipment = db.get(Equipment, equipment_id)

    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )

    update_data = equipment_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(equipment, field, value)

    db.commit()
    db.refresh(equipment)

    return equipment
