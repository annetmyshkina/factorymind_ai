"""Административное управление машинными ключами оборудования."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, require_admin
from app.core.database import get_db
from app.equipment.api_key_schemas import (
    EquipmentAPIKeyCreate,
    EquipmentAPIKeyCreatedResponse,
    EquipmentAPIKeyResponse,
)
from app.equipment.api_keys import (
    issue_equipment_api_key,
    list_equipment_api_keys,
    revoke_equipment_api_key,
)
from app.equipment.models import Equipment, EquipmentAPIKey

router = APIRouter(
    prefix="/equipment",
    tags=["Equipment API keys"],
    dependencies=[Depends(require_admin)],
)


def _get_equipment_or_404(db: Session, equipment_id: int) -> Equipment:
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        )
    return equipment


@router.post(
    "/{equipment_id}/api-keys",
    response_model=EquipmentAPIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_equipment_api_key(
    equipment_id: int,
    payload: EquipmentAPIKeyCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> EquipmentAPIKeyCreatedResponse:
    _get_equipment_or_404(db, equipment_id)
    api_key, raw_key = issue_equipment_api_key(
        db,
        equipment_id=equipment_id,
        name=payload.name,
        created_by_user_id=current_user.id,
        expires_at=payload.expires_at,
    )
    metadata = EquipmentAPIKeyResponse.model_validate(api_key)
    return EquipmentAPIKeyCreatedResponse(
        **metadata.model_dump(),
        api_key=raw_key,
    )


@router.get(
    "/{equipment_id}/api-keys",
    response_model=list[EquipmentAPIKeyResponse],
)
def read_equipment_api_keys(
    equipment_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> list[EquipmentAPIKey]:
    _get_equipment_or_404(db, equipment_id)
    return list_equipment_api_keys(db, equipment_id)


@router.post(
    "/{equipment_id}/api-keys/{api_key_id}/revoke",
    response_model=EquipmentAPIKeyResponse,
)
def revoke_api_key(
    equipment_id: int,
    api_key_id: int,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> EquipmentAPIKey:
    _get_equipment_or_404(db, equipment_id)
    api_key = db.get(EquipmentAPIKey, api_key_id)
    if api_key is None or api_key.equipment_id != equipment_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ключ оборудования не найден",
        )
    return revoke_equipment_api_key(
        db,
        api_key,
        revoked_by_user_id=current_user.id,
    )
