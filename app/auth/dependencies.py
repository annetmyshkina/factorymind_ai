"""Единые FastAPI-зависимости для аутентификации и RBAC."""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.models import User, UserRole
from app.auth.security import decode_access_token
from app.core.database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется действующая учётная запись",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError:
        raise _unauthorized() from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: UserRole) -> Callable[[CurrentUser], User]:
    allowed = frozenset(allowed_roles)

    def check_role(current_user: CurrentUser) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этой операции",
            )
        return current_user

    return check_role


require_authenticated = get_current_user
require_operator = require_roles(
    UserRole.OPERATOR,
    UserRole.ENGINEER,
    UserRole.ADMIN,
)
require_engineer = require_roles(UserRole.ENGINEER, UserRole.ADMIN)
require_admin = require_roles(UserRole.ADMIN)
