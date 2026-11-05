"""Схемы API журнала вызовов LLM."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


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


class GenerationParameters(BaseModel):
    """Поддерживаемые параметры генерации одного прогона."""

    model_config = ConfigDict(extra="forbid")

    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)


CriterionTerm = Annotated[str, Field(min_length=1)]
CriterionName = Annotated[str, Field(min_length=1, max_length=100)]


class DeterministicCriterion(BaseModel):
    """Один воспроизводимый критерий проверки текста ответа."""

    model_config = ConfigDict(extra="forbid")

    evaluator: Literal["contains_all", "contains_any", "excludes_all"]
    terms: list[CriterionTerm] = Field(min_length=1)
    case_sensitive: bool = False


class ExperimentRunCreate(BaseModel):
    """Запрос на создание прогона эксперимента."""

    provider: Literal["ollama", "compatible"] = Field(
        description="Имя провайдера",
    )
    model: str = Field(
        min_length=1,
        max_length=100,
        description="Имя модели",
    )
    parameters: GenerationParameters = Field(
        default_factory=GenerationParameters,
        description="Параметры генерации (temperature, max_tokens, ...)",
    )


class ExperimentCreate(BaseModel):
    """Атомарное создание эксперимента и набора его прогонов."""

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
        gt=0,
        description="ID неизменяемой версии промпта",
    )
    scenario: dict[str, object] = Field(
        min_length=1,
        description="Входные данные сценария (JSON)",
    )
    criteria: dict[CriterionName, DeterministicCriterion] = Field(
        min_length=1,
        description="Именованные критерии детерминированной оценки",
    )
    runs: list[ExperimentRunCreate] = Field(
        min_length=1,
        description="Сравниваемые провайдеры и модели",
    )

    @model_validator(mode="after")
    def runs_are_unique(self) -> "ExperimentCreate":
        keys = [(run.provider, run.model) for run in self.runs]
        if len(keys) != len(set(keys)):
            raise ValueError("Прогоны provider/model не должны повторяться")
        return self


class ExperimentResponse(BaseModel):
    """Эксперимент в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="ID эксперимента")
    name: str = Field(description="Название")
    description: str | None = Field(description="Описание")
    prompt_version_id: int = Field(description="ID версии промпта")
    scenario: dict[str, object] = Field(description="Сценарий")
    criteria: dict[str, object] = Field(description="Критерии оценки")
    created_at: AwareDatetime = Field(description="Создан (UTC)")


class ExperimentRunResponse(BaseModel):
    """Прогон эксперимента в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="ID прогона")
    experiment_id: int = Field(description="ID эксперимента")
    provider: str = Field(description="Провайдер")
    model: str = Field(description="Модель")
    parameters: dict[str, object] = Field(description="Параметры генерации")
    status: ExperimentRunStatus = Field(description="Статус прогона")
    error: str | None = Field(description="Текст ошибки (если failed)")
    started_at: AwareDatetime | None = Field(description="Начат (UTC)")
    finished_at: AwareDatetime | None = Field(description="Завершён (UTC)")
    created_at: AwareDatetime = Field(description="Создан (UTC)")


class EvaluationResultResponse(BaseModel):
    """Независимая оценка ответа по одному критерию."""

    model_config = ConfigDict(from_attributes=True)

    criterion: str
    score: int = Field(ge=0, le=2)
    evidence: dict[str, object]
    comment: str


class EvaluationResponse(BaseModel):
    """Детерминированная оценка сохранённого вызова."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    llm_call_id: int
    evaluator: str
    summary: dict[str, object]
    results: list[EvaluationResultResponse]
    created_at: AwareDatetime


class ExperimentRunDetailResponse(ExperimentRunResponse):
    """Прогон вместе с вызовом модели и оценкой."""

    call: LLMCallResponse | None
    evaluation: EvaluationResponse | None


class ExperimentDetailResponse(ExperimentResponse):
    """Эксперимент + прогоны."""

    runs: list[ExperimentRunDetailResponse] = Field(
        description="Прогоны эксперимента",
    )


class ExperimentReportRun(BaseModel):
    """Одна строка сравнительного отчёта."""

    provider: str
    model: str
    actual_model: str | None
    status: ExperimentRunStatus
    error: str | None
    response_text: str | None
    latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    evaluation: EvaluationResponse | None


class ExperimentReportResponse(BaseModel):
    """Сравнительный отчёт без непрозрачного общего балла."""

    experiment_id: int
    name: str
    prompt_version_id: int
    run_counts: dict[str, int]
    runs: list[ExperimentReportRun]
