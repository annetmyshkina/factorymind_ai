import pytest
from sqlalchemy import select

from app.ai.contracts import ChatMessage, LLMResponse, LLMUsage
from app.ai.errors import LLMResponseError, LLMTimeoutError
from app.ai.models import LLMCall
from app.ai.providers.base import LLMProvider
from app.ai.service import execute_call

MESSAGES = [
    ChatMessage(role="system", content="Ты аналитик инцидентов"),
    ChatMessage(role="user", content="Что случилось?"),
]


class FakeProvider(LLMProvider):
    name = "fake"
    model = "fake-default"

    def __init__(
        self,
        *,
        response: LLMResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    def close(self) -> None:
        """У тестового провайдера нет внешних ресурсов."""


def test_execute_call_saves_successful_call(db_session) -> None:
    provider = FakeProvider(
        response=LLMResponse(
            provider="fake",
            model="fake-model-2026-01",
            content="Возможен перегрев",
            latency_ms=42,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
        ),
    )

    call = execute_call(
        db_session,
        provider,
        MESSAGES,
        temperature=0.3,
        max_tokens=256,
        prompt_version="v1",
    )

    assert call.id > 0
    assert call.provider == "fake"
    assert call.model == "fake-model-2026-01"
    assert call.prompt_version == "v1"
    assert call.status == "success"
    assert call.response_text == "Возможен перегрев"
    assert call.error_type is None
    assert call.error_message is None
    assert call.latency_ms == 42
    assert call.prompt_tokens == 10
    assert call.completion_tokens == 5
    assert call.request_messages == [
        {"role": "system", "content": "Ты аналитик инцидентов"},
        {"role": "user", "content": "Что случилось?"},
    ]
    assert call.parameters == {"temperature": 0.3, "max_tokens": 256}
    assert call.created_at.tzinfo is not None

    assert provider.calls == [
        {
            "messages": MESSAGES,
            "model": None,
            "temperature": 0.3,
            "max_tokens": 256,
        },
    ]

    db_session.expire_all()
    saved = db_session.scalar(select(LLMCall))
    assert saved is not None
    assert saved.id == call.id


def test_execute_call_saves_timeout(db_session) -> None:
    provider = FakeProvider(
        error=LLMTimeoutError("Ollama не ответил", provider="fake"),
    )

    call = execute_call(db_session, provider, MESSAGES)

    assert call.status == "error"
    assert call.error_type == "timeout"
    assert call.error_message == "Ollama не ответил"
    assert call.response_text is None
    assert call.prompt_tokens is None
    assert call.completion_tokens is None
    assert call.parameters == {"temperature": 0.0, "max_tokens": None}
    assert call.latency_ms >= 0

    db_session.expire_all()
    saved = db_session.scalar(select(LLMCall))
    assert saved is not None
    assert saved.status == "error"


def test_execute_call_saves_response_error(db_session) -> None:
    provider = FakeProvider(
        error=LLMResponseError("Некорректный ответ", provider="fake"),
    )

    call = execute_call(db_session, provider, MESSAGES)

    assert call.status == "error"
    assert call.error_type == "response_error"
    assert call.error_message == "Некорректный ответ"


def test_execute_call_rejects_unexpected_error(db_session) -> None:
    provider = FakeProvider(error=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        execute_call(db_session, provider, MESSAGES)

    assert db_session.scalar(select(LLMCall)) is None
