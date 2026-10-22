from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EquipmentCreate(BaseModel):
    """Данные для создания оборудования."""

    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    equipment_type: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=100)


class EquipmentUpdate(BaseModel):
    """Данные для частичного обновления оборудования."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    equipment_type: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        """Проверяет, что передано хотя бы одно поле и значения не равны None."""
        if not self.model_fields_set:
            raise ValueError("Необходимо передать хотя бы одно поле для обновления")

        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"Поле '{field}' не может быть null")

        return self


class EquipmentResponse(BaseModel):
    """Данные оборудования, возвращаемые клиенту."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    equipment_type: str
    location: str
    is_active: bool
