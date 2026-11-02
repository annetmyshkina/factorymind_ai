"""Ошибки взаимодействия с провайдерами LLM."""


class LLMProviderError(Exception):
    """Провайдер LLM недоступен или вернул ошибку."""

    code = "provider_error"

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class LLMTimeoutError(LLMProviderError):
    """Провайдер не ответил за отведённое время."""

    code = "timeout"


class LLMResponseError(LLMProviderError):
    """Ответ провайдера не соответствует ожидаемому формату."""

    code = "response_error"


class UnknownProviderError(ValueError):
    """Запрошен неизвестный провайдер LLM."""


class ProviderNotConfiguredError(ValueError):
    """Для провайдера не заданы обязательные настройки."""
