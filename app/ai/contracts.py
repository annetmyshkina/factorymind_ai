"""Контракты обмена с провайдерами LLM."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Сообщение чата в формате, общем для провайдеров."""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Расход токенов, если провайдер его сообщает."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Нормализованный ответ модели."""

    provider: str
    model: str
    content: str
    latency_ms: int
    usage: LLMUsage = field(default_factory=LLMUsage)
