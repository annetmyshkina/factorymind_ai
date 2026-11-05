"""Провайдер локальных моделей Ollama."""

import time
from typing import Any

import httpx2

from app.ai.contracts import ChatMessage, LLMResponse, LLMUsage
from app.ai.errors import LLMProviderError, LLMResponseError, LLMTimeoutError
from app.ai.providers._utils import elapsed_ms, optional_int


class OllamaProvider:
    """Вызывает модель через Ollama HTTP API."""

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx2.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
        )

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        model_name = model or self.model
        payload = {
            "model": model_name,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": False,
            "options": options,
        }

        started = time.perf_counter()
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx2.TimeoutException as exc:
            raise LLMTimeoutError(
                "Ollama не ответил за отведённое время",
                provider=self.name,
            ) from exc
        except httpx2.HTTPError as exc:
            raise LLMProviderError(
                f"Ollama вернул ошибку: {exc}",
                provider=self.name,
            ) from exc

        latency_ms = elapsed_ms(started)

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseError(
                "Ollama вернул не-JSON ответ",
                provider=self.name,
            ) from exc

        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content:
            raise LLMResponseError(
                "В ответе Ollama нет message.content",
                provider=self.name,
            )

        return LLMResponse(
            provider=self.name,
            model=str(data.get("model") or model_name),
            content=content,
            latency_ms=latency_ms,
            usage=LLMUsage(
                prompt_tokens=optional_int(data.get("prompt_eval_count")),
                completion_tokens=optional_int(data.get("eval_count")),
            ),
        )

    def close(self) -> None:
        """Закрывает HTTP-клиент провайдера."""
        self._client.close()
