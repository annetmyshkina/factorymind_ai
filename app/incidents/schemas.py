from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

IncidentStatus = Literal["open", "in_progress", "resolved", "closed"]
IncidentSeverity = Literal["low", "medium", "high", "critical"]


class IncidentCreate(BaseModel):
    """Данные для создания инцидента."""

    equipment_id: int = Field(
        description="ID оборудования, к которому относится инцидент",
    )
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Краткое описание инцидента",
    )
    description: str | None = Field(
        default=None,
        description="Подробное описание (опционально)",
    )
    severity: IncidentSeverity = Field(
        default="medium",
        description="Уровень серьёзности инцидента",
    )
    assigned_to: str | None = Field(
        default=None,
        max_length=100,
        description="Исполнитель (опционально)",
    )


class IncidentUpdate(BaseModel):
    """Обновление инцидента (все поля опциональны)."""

    status: IncidentStatus | None = Field(
        default=None,
        description="Новый статус (переход валидируется системой состояний)",
    )
    assigned_to: str | None = Field(
        default=None,
        description="Новый исполнитель (null — снять)",
    )
    severity: IncidentSeverity | None = Field(
        default=None,
        description="Новый уровень серьёзности",
    )
    description: str | None = Field(
        default=None,
        description="Новое описание",
    )


class IncidentEventResponse(BaseModel):
    """Событие истории инцидента (аудит)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="ID события")
    event_type: str = Field(
        description="Тип события: created, status_changed, assigned, deviation_linked",
    )
    payload: dict | None = Field(
        default=None,
        description="Полезная нагрузка события (зависит от типа)",
    )
    created_at: AwareDatetime = Field(description="Время события (UTC)")


class IncidentResponse(BaseModel):
    """Инцидент в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="ID инцидента")
    equipment_id: int = Field(description="ID оборудования")
    title: str = Field(description="Краткое описание")
    description: str | None = Field(description="Подробное описание")
    status: IncidentStatus = Field(description="Текущий статус")
    severity: IncidentSeverity = Field(description="Уровень серьёзности")
    assigned_to: str | None = Field(description="Исполнитель")
    created_at: AwareDatetime = Field(description="Создан (UTC)")
    updated_at: AwareDatetime = Field(description="Обновлён (UTC)")
    resolved_at: AwareDatetime | None = Field(
        description="Решён (UTC), null если не решён",
    )


class IncidentDetailResponse(IncidentResponse):
    """Инцидент + связанные отклонения + история событий."""

    deviation_ids: list[int] = Field(
        description="ID отклонений, привязанных к инциденту",
    )
    events: list[IncidentEventResponse] = Field(
        description="История событий инцидента",
    )


class LinkDeviationRequest(BaseModel):
    """Запрос на привязку отклонения к инциденту."""

    deviation_id: int = Field(
        description="ID отклонения (одно отклонение — один инцидент)",
    )
