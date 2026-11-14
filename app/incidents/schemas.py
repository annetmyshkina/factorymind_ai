from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.knowledge.schemas import DocumentType

IncidentStatus = Literal["open", "in_progress", "resolved", "closed"]
IncidentSeverity = Literal["low", "medium", "high", "critical"]
AnalysisText = Annotated[str, Field(min_length=1, max_length=2000)]


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
        max_length=100,
        description="Новый исполнитель",
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
    equipment_code: str = Field(
        description="Код оборудования",
    )
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


class IncidentAnalysisCreate(BaseModel):
    """Запрос на диагностический анализ инцидента с retrieval."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=500)
    provider: Literal["ollama", "compatible"]
    model: str | None = Field(default=None, min_length=1, max_length=100)
    max_sources: int = Field(default=5, ge=1, le=10)


class IncidentAnalysisCitedItem(BaseModel):
    """Вывод модели с явными ссылками на переданные фрагменты."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: AnalysisText
    source_chunk_ids: list[int] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def source_ids_are_unique(self) -> Self:
        if len(self.source_chunk_ids) != len(set(self.source_chunk_ids)):
            raise ValueError("Ссылки на источники не должны повторяться")
        return self


class IncidentAnalysisResult(BaseModel):
    """Проверенная структура диагностической рекомендации."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    observed_facts: list[AnalysisText] = Field(default_factory=list, max_length=30)
    possible_causes: list[IncidentAnalysisCitedItem] = Field(
        default_factory=list,
        max_length=20,
    )
    required_checks: list[IncidentAnalysisCitedItem] = Field(
        default_factory=list,
        max_length=20,
    )
    recommendations: list[IncidentAnalysisCitedItem] = Field(
        default_factory=list,
        max_length=20,
    )
    insufficient_data: list[AnalysisText] = Field(default_factory=list, max_length=20)
    warnings: list[AnalysisText] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def contains_conclusion_or_limitation(self) -> Self:
        has_conclusion = bool(
            self.possible_causes or self.required_checks or self.recommendations
        )
        if not has_conclusion and not self.insufficient_data:
            raise ValueError(
                "Ответ должен содержать выводы или указание на недостаток данных",
            )
        return self


class IncidentAnalysisSourceResponse(BaseModel):
    """Источник, переданный модели и доступный для проверки цитаты."""

    rank: int = Field(gt=0)
    score: float = Field(ge=0)
    chunk_id: int
    chunk_index: int
    content: str
    checksum_sha256: str
    page_start: int | None
    page_end: int | None
    document_id: int
    document_title: str
    document_type: DocumentType
    source_name: str
    document_version_id: int
    document_version: str
    source_uri: str | None
    citation: str


class IncidentAnalysisResponse(BaseModel):
    """Сохранённая версия анализа с точным набором источников."""

    id: int
    incident_id: int
    llm_call_id: int | None
    query: str
    prompt_version: str
    status: Literal["completed", "insufficient"]
    result: IncidentAnalysisResult
    sources: list[IncidentAnalysisSourceResponse]
    created_at: AwareDatetime
