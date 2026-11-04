"""Схемы API журнала вызовов LLM."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ChatMessageSchema(BaseModel):
    """Сообщение чата в запросе к модели."""

    role: Literal["system", "user", "assistant"] = Field(
        description="Роль автора сообщения",
    )
    content: str = Field(
        min_length=1,
        description="Текст сообщения",
    )


class LLMCallCreate(BaseModel):
    """Запрос на вызов модели."""

    provider: str = Field(
        min_length=1,
        max_length=50,
        description="Имя провайдера: ollama или compatible",
    )
    model: str | None = Field(
        default=None,
        max_length=100,
        description="Переопределение модели по умолчанию",
    )
    messages: list[ChatMessageSchema] = Field(
        min_length=1,
        description="Сообщения чата",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Температура генерации",
    )
    max_tokens: int | None = Field(
        default=None,
        gt=0,
        description="Ограничение длины ответа",
    )
    prompt_version: str | None = Field(
        default=None,
        max_length=50,
        description="Метка версии промпта для воспроизводимости",
    )


class LLMCallResponse(BaseModel):
    """Сохранённый вызов модели."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="ID вызова")
    provider: str = Field(description="Провайдер")
    model: str = Field(description="Фактическая модель")
    prompt_version: str | None = Field(description="Версия промпта")
    request_messages: list[dict[str, str]] = Field(
        description="Входные сообщения",
    )
    parameters: dict[str, object] = Field(
        description="Параметры генерации",
    )
    response_text: str | None = Field(description="Текст ответа")
    status: Literal["success", "error"] = Field(description="Статус вызова")
    error_type: str | None = Field(description="Тип ошибки")
    error_message: str | None = Field(description="Текст ошибки")
    latency_ms: int = Field(description="Длительность вызова, мс")
    prompt_tokens: int | None = Field(description="Токены запроса")
    completion_tokens: int | None = Field(description="Токены ответа")
    created_at: AwareDatetime = Field(description="Время вызова (UTC)")


class PromptVersionCreate(BaseModel):
    """Запрос на создание версии промпта."""

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Имя промпта",
    )
    version: str = Field(
        min_length=1,
        max_length=50,
        description="Версия промпта",
    )
    content: str = Field(
        min_length=1,
        description="Текст промпта",
    )


class PromptVersionResponse(BaseModel):
    """Сохранённая версия промпта."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="ID версии")
    name: str = Field(description="Имя промпта")
    version: str = Field(description="Версия промпта")
    content: str = Field(description="Текст промпта")
    created_at: AwareDatetime = Field(description="Время создания (UTC)")


# ---------- Эксперименты (4.2) ----------


ExperimentRunStatus = Literal["pending", "running", "succeeded", "failed"]


class ExperimentCreate(BaseModel):
    """Запрос на создание эксперимента."""

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Название эксперимента",
    )
    description: str | None = Field(
        default=None,
        description="Описание эксперимента",
    )
    prompt_version_id: int = Field(
        description="ID неизменяемой версии промпта",
    )
    scenario: dict = Field(
        description="Входные данные сценария (JSON)",
    )
    criteria: dict = Field(
        description="Критерии оценки (JSON)",
    )


class ExperimentResponse(BaseModel):
    """Эксперимент в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="ID эксперимента")
    name: str = Field(description="Название")
    description: str | None = Field(description="Описание")
    prompt_version_id: int = Field(description="ID версии промпта")
    scenario: dict = Field(description="Сценарий")
    criteria: dict = Field(description="Критерии оценки")
    created_at: AwareDatetime = Field(description="Создан (UTC)")


class ExperimentRunCreate(BaseModel):
    """Запрос на создание прогона эксперимента."""

    provider: str = Field(
        min_length=1,
        max_length=50,
        description="Имя провайдера",
    )
    model: str = Field(
        min_length=1,
        max_length=100,
        description="Имя модели",
    )
    parameters: dict = Field(
        default_factory=dict,
        description="Параметры генерации (temperature, max_tokens, ...)",
    )


class ExperimentRunResponse(BaseModel):
    """Прогон эксперимента в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="ID прогона")
    experiment_id: int = Field(description="ID эксперимента")
    provider: str = Field(description="Провайдер")
    model: str = Field(description="Модель")
    parameters: dict = Field(description="Параметры генерации")
    status: ExperimentRunStatus = Field(description="Статус прогона")
    error: str | None = Field(description="Текст ошибки (если failed)")
    started_at: AwareDatetime | None = Field(description="Начат (UTC)")
    finished_at: AwareDatetime | None = Field(description="Завершён (UTC)")
    created_at: AwareDatetime = Field(description="Создан (UTC)")


class ExperimentDetailResponse(ExperimentResponse):
    """Эксперимент + прогоны."""

    runs: list[ExperimentRunResponse] = Field(
        description="Прогоны эксперимента",
    )
