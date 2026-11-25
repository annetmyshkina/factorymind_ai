"""Выпуск, проверка и отзыв машинных ключей оборудования."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.equipment.models import EquipmentAPIKey

KEY_PATTERN = re.compile(
    r"^fmk_(?P<key_id>[0-9a-f]{16})_(?P<secret>[A-Za-z0-9_-]{43})$",
)


def _digest(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def issue_equipment_api_key(
    db: Session,
    *,
    equipment_id: int,
    name: str,
    created_by_user_id: int,
    expires_at: datetime | None,
) -> tuple[EquipmentAPIKey, str]:
    key_id = secrets.token_hex(8)
    raw_key = f"fmk_{key_id}_{secrets.token_urlsafe(32)}"
    api_key = EquipmentAPIKey(
        equipment_id=equipment_id,
        name=name,
        key_id=key_id,
        secret_hash=_digest(raw_key),
        created_by_user_id=created_by_user_id,
        expires_at=expires_at,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, raw_key


def list_equipment_api_keys(
    db: Session,
    equipment_id: int,
) -> list[EquipmentAPIKey]:
    statement = (
        select(EquipmentAPIKey)
        .where(EquipmentAPIKey.equipment_id == equipment_id)
        .order_by(EquipmentAPIKey.created_at.desc(), EquipmentAPIKey.id.desc())
    )
    return list(db.scalars(statement).all())


def authenticate_equipment_api_key(
    db: Session,
    raw_key: str,
    *,
    now: datetime | None = None,
) -> EquipmentAPIKey | None:
    match = KEY_PATTERN.fullmatch(raw_key)
    if match is None:
        return None

    api_key = db.scalar(
        select(EquipmentAPIKey).where(
            EquipmentAPIKey.key_id == match.group("key_id"),
        ),
    )
    current_time = now or datetime.now(UTC)
    if (
        api_key is None
        or not api_key.is_active
        or api_key.revoked_at is not None
        or (api_key.expires_at is not None and api_key.expires_at <= current_time)
        or not hmac.compare_digest(api_key.secret_hash, _digest(raw_key))
    ):
        return None
    return api_key


def revoke_equipment_api_key(
    db: Session,
    api_key: EquipmentAPIKey,
    *,
    revoked_by_user_id: int,
) -> EquipmentAPIKey:
    if api_key.is_active:
        api_key.is_active = False
        api_key.revoked_at = datetime.now(UTC)
        api_key.revoked_by_user_id = revoked_by_user_id
        db.commit()
        db.refresh(api_key)
    return api_key
