"""Операции с локальными пользователями."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User, UserRole
from app.auth.security import hash_password, verify_dummy_password, verify_password


class UsernameConflictError(ValueError):
    """Логин уже занят."""


class UserNotFoundError(LookupError):
    """Пользователь не найден."""


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_dummy_password(password)
        return None
    password_matches = verify_password(password, user.password_hash)
    if not user.is_active or not password_matches:
        return None
    return user


def ensure_bootstrap_admin(
    db: Session,
    *,
    username: str,
    password: str,
) -> tuple[User, bool]:
    """Создаёт локального администратора один раз, не меняя его пароль позже."""
    user = db.scalar(select(User).where(User.username == username))
    if user is not None:
        return user, False

    user = User(
        username=username,
        full_name="Local administrator",
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(User).where(User.username == username))
        if existing is None:
            raise
        return existing, False
    db.refresh(user)
    return user, True


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    full_name: str | None,
    role: UserRole,
) -> User:
    user = User(
        username=username,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise UsernameConflictError from None
    db.refresh(user)
    return user


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username)))


def update_user(
    db: Session,
    user_id: int,
    *,
    password: str | None,
    full_name: str | None,
    role: UserRole | None,
    is_active: bool | None,
    fields_set: set[str],
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError
    if password is not None:
        user.password_hash = hash_password(password)
    if "full_name" in fields_set:
        user.full_name = full_name
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user
