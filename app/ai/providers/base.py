"""Общий интерфейс провайдера LLM."""

from abc import ABC, abstractmethod

from app.ai.contracts import ChatMessage, LLMResponse


class LLMProvider(ABC):
    """Провайдер, умеющий выполнять chat-запрос к модели."""

    name: str
    model: str

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Возвращает нормализованный ответ модели."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Освобождает сетевые ресурсы провайдера."""
        raise NotImplementedError
