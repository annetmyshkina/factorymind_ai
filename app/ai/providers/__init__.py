"""Фабрика провайдеров LLM."""

import httpx2

from app.ai.errors import ProviderNotConfiguredError, UnknownProviderError
from app.ai.providers.base import LLMProvider
from app.ai.providers.compatible import CompatibleProvider
from app.ai.providers.ollama import OllamaProvider
from app.core.config import Settings


def build_provider(
    name: str,
    settings: Settings,
    *,
    model: str | None = None,
    transport: httpx2.BaseTransport | None = None,
) -> LLMProvider:
    """Создаёт провайдера по имени, используя настройки приложения.

    model переопределяет модель по умолчанию, transport подменяет
    HTTP-транспорт в тестах.
    """
    if name == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=model or settings.ollama_model,
            timeout=settings.llm_timeout_seconds,
            transport=transport,
        )

    if name == "compatible":
        base_url = settings.compatible_base_url
        if not base_url:
            raise ProviderNotConfiguredError(
                "Не задан COMPATIBLE_BASE_URL",
            )

        resolved_model = model or settings.compatible_model
        if not resolved_model:
            raise ProviderNotConfiguredError(
                "Не задана модель: укажите COMPATIBLE_MODEL или model в запросе",
            )

        return CompatibleProvider(
            base_url=base_url,
            model=resolved_model,
            api_key=settings.compatible_api_key,
            auth_scheme=settings.compatible_auth_scheme,
            timeout=settings.llm_timeout_seconds,
            transport=transport,
        )

    raise UnknownProviderError(f"Неизвестный провайдер LLM: {name}")
