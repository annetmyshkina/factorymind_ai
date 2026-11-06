"""Ошибки взаимодействия с провайдерами LLM."""


class LLMProviderError(Exception):
    """Провайдер LLM недоступен или вернул ошибку."""

    code = "provider_error"
    retryable = True

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class LLMTimeoutError(LLMProviderError):
    """Провайдер не ответил за отведённое время."""

    code = "timeout"


class LLMResponseError(LLMProviderError):
    """Ответ провайдера не соответствует ожидаемому формату."""

    code = "response_error"
    retryable = False


class LLMRequestError(LLMProviderError):
    """Провайдер отклонил заведомо некорректный запрос."""

    code = "request_error"
    retryable = False


class LLMRateLimitError(LLMProviderError):
    """Провайдер временно ограничил частоту запросов."""

    code = "rate_limit"


class UnknownProviderError(ValueError):
    """Запрошен неизвестный провайдер LLM."""


class ProviderNotConfiguredError(ValueError):
    """Для провайдера не заданы обязательные настройки."""
