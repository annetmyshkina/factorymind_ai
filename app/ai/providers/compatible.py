"""Провайдер моделей с Chat Completions-совместимым API."""

import time
from typing import Any

import httpx2

from app.ai.contracts import ChatMessage, LLMResponse, LLMUsage
from app.ai.errors import LLMProviderError, LLMResponseError, LLMTimeoutError
from app.ai.providers._utils import elapsed_ms, optional_int


class CompatibleProvider:
    """Вызывает модель через Chat Completions-совместимый /chat/completions.

    Подходит для провайдеров (например, VseGPT) и для локальных
    совместимых серверов: меняются только base_url, ключ и модель.
    """

    name = "compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        auth_scheme: str = "Bearer",
        timeout: float = 60.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self.model = model
        headers = {}
        if api_key:
            headers["Authorization"] = f"{auth_scheme} {api_key}".strip()
        self._client = httpx2.Client(
            base_url=base_url,
            timeout=timeout,
            headers=headers,
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
        model_name = model or self.model
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        started = time.perf_counter()
        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except httpx2.TimeoutException as exc:
            raise LLMTimeoutError(
                "Провайдер не ответил за отведённое время",
                provider=self.name,
            ) from exc
        except httpx2.HTTPError as exc:
            raise LLMProviderError(
                f"Провайдер вернул ошибку: {exc}",
                provider=self.name,
            ) from exc

        latency_ms = elapsed_ms(started)

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseError(
                "Провайдер вернул не-JSON ответ",
                provider=self.name,
            ) from exc

        choices = data.get("choices") if isinstance(data, dict) else None
        try:
            content = choices[0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as exc:
            raise LLMResponseError(
                "В ответе провайдера нет choices[0].message.content",
                provider=self.name,
            ) from exc

        if not isinstance(content, str) or not content:
            raise LLMResponseError(
                "Провайдер вернул пустой ответ",
                provider=self.name,
            )

        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = {}

        return LLMResponse(
            provider=self.name,
            model=str(data.get("model") or model_name),
            content=content,
            latency_ms=latency_ms,
            usage=LLMUsage(
                prompt_tokens=optional_int(usage.get("prompt_tokens")),
                completion_tokens=optional_int(usage.get("completion_tokens")),
            ),
        )

    def close(self) -> None:
        """Закрывает HTTP-клиент провайдера."""
        self._client.close()
