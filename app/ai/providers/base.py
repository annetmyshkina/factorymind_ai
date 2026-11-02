"""Общий интерфейс провайдера LLM."""

from typing import Protocol

from app.ai.contracts import ChatMessage, LLMResponse


class LLMProvider(Protocol):
    """Провайдер, умеющий выполнять chat-запрос к модели."""

    name: str
    model: str

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Возвращает нормализованный ответ модели."""
        ...
