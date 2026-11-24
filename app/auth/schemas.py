"""Контракты API аутентификации."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.auth.models import UserRole


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    password: SecretStr = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    password: SecretStr | None = Field(default=None, min_length=8, max_length=128)
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def contains_change(self) -> "UserUpdate":
        has_change = (
            "full_name" in self.model_fields_set
            or self.password is not None
            or self.role is not None
            or self.is_active is not None
        )
        if not has_change:
            raise ValueError("Укажите хотя бы одно изменение пользователя")
        return self
