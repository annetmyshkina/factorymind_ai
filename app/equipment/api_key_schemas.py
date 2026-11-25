"""Контракты управления машинными ключами оборудования."""

from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class EquipmentAPIKeyCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    expires_at: AwareDatetime | None = None

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(
        cls,
        value: AwareDatetime | None,
    ) -> AwareDatetime | None:
        if value is None:
            return None
        value = value.astimezone(UTC)
        if value <= datetime.now(UTC):
            raise ValueError("Срок действия ключа должен быть в будущем")
        return value


class EquipmentAPIKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    name: str
    key_prefix: str
    is_active: bool
    created_by_user_id: int
    revoked_by_user_id: int | None
    created_at: AwareDatetime
    expires_at: AwareDatetime | None
    last_used_at: AwareDatetime | None
    revoked_at: AwareDatetime | None


class EquipmentAPIKeyCreatedResponse(EquipmentAPIKeyResponse):
    """Ответ выпуска ключа: открытое значение возвращается только один раз."""

    api_key: str
