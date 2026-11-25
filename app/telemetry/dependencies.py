"""Авторизация пользовательской и машинной записи телеметрии."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.dependencies import get_user_from_token
from app.auth.models import UserRole
from app.core.database import get_db
from app.equipment.api_keys import authenticate_equipment_api_key

optional_bearer = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)
optional_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


def authorize_telemetry_write(
    equipment_id: int,
    bearer_token: Annotated[str | None, Depends(optional_bearer)],
    raw_api_key: Annotated[str | None, Depends(optional_api_key)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Разрешает операторский JWT либо ключ указанного оборудования."""
    if bearer_token is not None:
        user = get_user_from_token(bearer_token, db)
        if user.role not in {
            UserRole.OPERATOR,
            UserRole.ENGINEER,
            UserRole.ADMIN,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этой операции",
            )
        return

    if raw_api_key is not None:
        api_key = authenticate_equipment_api_key(db, raw_api_key)
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуются действующие учётные данные",
            )
        if api_key.equipment_id != equipment_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ключ не разрешён для этого оборудования",
            )
        api_key.last_used_at = datetime.now(UTC)
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуются действующие учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
