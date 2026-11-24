"""Вход в систему и сведения о текущем пользователе."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, require_admin
from app.auth.schemas import (
    AccessTokenResponse,
    CurrentUserResponse,
    UserCreate,
    UserUpdate,
)
from app.auth.security import create_access_token
from app.auth.service import (
    UsernameConflictError,
    UserNotFoundError,
    authenticate_user,
    create_user,
    list_users,
    update_user,
)
from app.core.database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/token", response_model=AccessTokenResponse)
def issue_access_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> AccessTokenResponse:
    credentials_have_valid_length = (
        1 <= len(form.username) <= 64 and 1 <= len(form.password) <= 128
    )
    user = (
        authenticate_user(db, form.username, form.password)
        if credentials_have_valid_length
        else None
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = create_access_token(user.id)
    return AccessTokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=CurrentUserResponse)
def read_current_user(current_user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse.model_validate(current_user)


@router.post(
    "/users",
    response_model=CurrentUserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_local_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
) -> CurrentUserResponse:
    try:
        user = create_user(
            db,
            username=payload.username,
            password=payload.password.get_secret_value(),
            full_name=payload.full_name,
            role=payload.role,
        )
    except UsernameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким логином уже существует",
        ) from exc
    return CurrentUserResponse.model_validate(user)


@router.get(
    "/users",
    response_model=list[CurrentUserResponse],
    dependencies=[Depends(require_admin)],
)
def read_users(
    db: Annotated[Session, Depends(get_db)],
) -> list[CurrentUserResponse]:
    return [CurrentUserResponse.model_validate(user) for user in list_users(db)]


@router.patch(
    "/users/{user_id}",
    response_model=CurrentUserResponse,
    dependencies=[Depends(require_admin)],
)
def update_local_user(
    user_id: int,
    payload: UserUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CurrentUserResponse:
    if user_id == current_user.id and (
        payload.is_active is False
        or (payload.role is not None and payload.role != current_user.role)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нельзя отключить или понизить собственную учётную запись",
        )
    try:
        user = update_user(
            db,
            user_id,
            password=(
                payload.password.get_secret_value()
                if payload.password is not None
                else None
            ),
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
            fields_set=payload.model_fields_set,
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        ) from exc
    return CurrentUserResponse.model_validate(user)
