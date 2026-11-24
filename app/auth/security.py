"""Хеширование паролей и выпуск короткоживущих access-токенов."""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("factorymind-dummy-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    return password_hash.verify(password, encoded_hash)


def verify_dummy_password(password: str) -> None:
    """Сглаживает разницу времени между неизвестным и известным логином."""
    password_hash.verify(password, DUMMY_PASSWORD_HASH)


def create_access_token(user_id: int) -> tuple[str, int]:
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.auth_access_token_minutes)
    expires_at = now + lifetime
    token = jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "iss": settings.auth_jwt_issuer,
            "aud": settings.auth_jwt_audience,
            "iat": now,
            "exp": expires_at,
        },
        settings.auth_jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> int:
    payload = jwt.decode(
        token,
        settings.auth_jwt_secret.get_secret_value(),
        algorithms=[ALGORITHM],
        audience=settings.auth_jwt_audience,
        issuer=settings.auth_jwt_issuer,
        options={"require": ["sub", "type", "iss", "aud", "iat", "exp"]},
    )
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("Неверный тип токена")
    try:
        return int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise jwt.InvalidTokenError("Неверный subject токена") from exc
