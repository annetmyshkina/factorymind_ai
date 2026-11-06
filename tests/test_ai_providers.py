import json
from typing import Any

import httpx2
import pytest

from app.ai.contracts import ChatMessage
from app.ai.errors import (
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
    ProviderNotConfiguredError,
    UnknownProviderError,
)
from app.ai.providers.compatible import CompatibleProvider
from app.ai.providers.factory import build_provider
from app.ai.providers.ollama import OllamaProvider
from app.core.config import Settings

MESSAGES = [ChatMessage(role="user", content="Почему выросла температура?")]


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, postgres_password="test", **overrides)


def _mock(handler) -> httpx2.MockTransport:
    return httpx2.MockTransport(handler)


def test_ollama_sends_request_and_parses_response() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200,
            json={
                "model": "llama3.1",
                "message": {"role": "assistant", "content": "Возможен перегрев"},
                "prompt_eval_count": 12,
                "eval_count": 5,
            },
        )

    provider = OllamaProvider(
        base_url="http://llm.test",
        model="llama3.1",
        transport=_mock(handler),
    )

    response = provider.chat(MESSAGES, temperature=0.2, max_tokens=128)

    request = captured[0]
    assert str(request.url) == "http://llm.test/api/chat"
    assert json.loads(request.content) == {
        "model": "llama3.1",
        "messages": [
            {"role": "user", "content": "Почему выросла температура?"},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 128},
    }
    assert response.provider == "ollama"
    assert response.model == "llama3.1"
    assert response.content == "Возможен перегрев"
    assert response.latency_ms >= 0
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 5


def test_ollama_default_options_without_max_tokens() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200,
            json={"message": {"content": "ok"}},
        )

    provider = OllamaProvider(
        base_url="http://llm.test",
        model="llama3.1",
        transport=_mock(handler),
    )
    response = provider.chat(MESSAGES)

    assert json.loads(captured[0].content)["options"] == {"temperature": 0.0}
    assert response.model == "llama3.1"
    assert response.usage.prompt_tokens is None
    assert response.usage.completion_tokens is None


def test_ollama_timeout_maps_to_domain_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timeout")

    provider = OllamaProvider(
        base_url="http://llm.test",
        model="llama3.1",
        transport=_mock(handler),
    )

    with pytest.raises(LLMTimeoutError):
        provider.chat(MESSAGES)


def test_ollama_http_error_maps_to_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"error": "boom"})

    provider = OllamaProvider(
        base_url="http://llm.test",
        model="llama3.1",
        transport=_mock(handler),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.chat(MESSAGES)

    assert not isinstance(exc_info.value, LLMTimeoutError)
    assert exc_info.value.provider == "ollama"


def test_ollama_invalid_json_maps_to_response_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="not-json")

    provider = OllamaProvider(
        base_url="http://llm.test",
        model="llama3.1",
        transport=_mock(handler),
    )

    with pytest.raises(LLMResponseError):
        provider.chat(MESSAGES)


def test_ollama_missing_content_maps_to_response_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"message": {}})

    provider = OllamaProvider(
        base_url="http://llm.test",
        model="llama3.1",
        transport=_mock(handler),
    )

    with pytest.raises(LLMResponseError):
        provider.chat(MESSAGES)


def test_compatible_sends_request_and_parses_response() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200,
            json={
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [
                    {"message": {"role": "assistant", "content": "Ответ"}},
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    provider = CompatibleProvider(
        base_url="https://api.test/v1",
        model="gpt-4o-mini",
        api_key="secret",
        transport=_mock(handler),
    )

    response = provider.chat(MESSAGES, temperature=0.1, max_tokens=64)

    request = captured[0]
    assert str(request.url) == "https://api.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"
    assert json.loads(request.content) == {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Почему выросла температура?"},
        ],
        "temperature": 0.1,
        "max_tokens": 64,
    }
    assert response.provider == "compatible"
    assert response.model == "gpt-4o-mini-2024-07-18"
    assert response.content == "Ответ"
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 4


def test_compatible_without_api_key_omits_authorization() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    provider = CompatibleProvider(
        base_url="https://api.test/v1",
        model="gpt-4o-mini",
        transport=_mock(handler),
    )
    provider.chat(MESSAGES)

    assert "authorization" not in captured[0].headers


def test_compatible_timeout_maps_to_domain_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("timeout")

    provider = CompatibleProvider(
        base_url="https://api.test/v1",
        model="gpt-4o-mini",
        transport=_mock(handler),
    )

    with pytest.raises(LLMTimeoutError):
        provider.chat(MESSAGES)


@pytest.mark.parametrize(
    ("status_code", "error_type", "retryable"),
    [
        (400, LLMRequestError, False),
        (429, LLMRateLimitError, True),
        (503, LLMProviderError, True),
    ],
)
def test_compatible_classifies_http_errors_for_retry(
    status_code: int,
    error_type: type[LLMProviderError],
    retryable: bool,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code, json={"error": "boom"})

    provider = CompatibleProvider(
        base_url="https://api.test/v1",
        model="gpt-4o-mini",
        transport=_mock(handler),
    )

    with pytest.raises(error_type) as exc_info:
        provider.chat(MESSAGES)

    assert exc_info.value.retryable is retryable


def test_compatible_missing_choices_maps_to_response_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"choices": []})

    provider = CompatibleProvider(
        base_url="https://api.test/v1",
        model="gpt-4o-mini",
        transport=_mock(handler),
    )

    with pytest.raises(LLMResponseError):
        provider.chat(MESSAGES)


def test_compatible_sends_model_override() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    provider = CompatibleProvider(
        base_url="https://api.test/v1",
        model="default-model",
        transport=_mock(handler),
    )

    response = provider.chat(MESSAGES, model="custom-model")

    assert json.loads(captured[0].content)["model"] == "custom-model"
    assert response.model == "custom-model"


def test_compatible_supports_custom_auth_scheme() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    provider = CompatibleProvider(
        base_url="https://api.test/v1",
        model="gpt-4o",
        api_key="key",
        auth_scheme="Api-Key",
        transport=_mock(handler),
    )
    provider.chat(MESSAGES)

    assert captured[0].headers["authorization"] == "Api-Key key"


def test_build_provider_uses_settings() -> None:
    settings = _settings(
        ollama_model="qwen2.5",
        compatible_base_url="https://api.test/v1",
        compatible_model="gpt-4o",
        compatible_api_key="key",
    )

    ollama = build_provider("ollama", settings)
    compatible = build_provider("compatible", settings)

    assert isinstance(ollama, OllamaProvider)
    assert ollama.model == "qwen2.5"
    assert isinstance(compatible, CompatibleProvider)
    assert compatible.model == "gpt-4o"


def test_build_provider_model_override() -> None:
    settings = _settings(
        compatible_base_url="https://api.test/v1",
        compatible_model="default-model",
    )

    provider = build_provider("compatible", settings, model="override")

    assert provider.model == "override"


def test_build_provider_requires_base_url() -> None:
    with pytest.raises(
        ProviderNotConfiguredError,
        match="COMPATIBLE_BASE_URL",
    ):
        build_provider("compatible", _settings())


def test_build_provider_requires_model() -> None:
    settings = _settings(compatible_base_url="https://api.test/v1")

    with pytest.raises(ProviderNotConfiguredError, match="модель"):
        build_provider("compatible", settings)


def test_build_provider_rejects_unknown_name() -> None:
    with pytest.raises(UnknownProviderError, match="Неизвестный провайдер"):
        build_provider("anthropic", _settings())
