from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import ChatMessage, LLMResponse, LLMUsage
from app.ai.errors import LLMProviderError, LLMResponseError, LLMTimeoutError
from app.ai.models import LLMCall
from app.ai.providers.base import LLMProvider
from app.ai.router import create_call
from app.ai.schemas import LLMCallCreate
from app.core.config import Settings


class FakeProvider(LLMProvider):
    name = "compatible"
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
        self.closed = False

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
        self.closed = True


def _payload(**overrides) -> dict:
    payload = {
        "provider": "compatible",
        "model": "fake-model",
        "messages": [
            {"role": "user", "content": "Почему выросла температура?"},
        ],
        "temperature": 0.1,
        "max_tokens": 64,
        "prompt_version": "v1",
    }
    payload.update(overrides)
    return payload


def _patch_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: FakeProvider,
) -> None:
    monkeypatch.setattr(
        "app.ai.router.build_provider",
        lambda *args, **kwargs: provider,
    )


def _insert_call(
    db_session: Session,
    *,
    provider: str = "compatible",
    call_status: str = "success",
    created_at: datetime | None = None,
) -> LLMCall:
    kwargs = {
        "provider": provider,
        "model": "model",
        "prompt_version": None,
        "request_messages": [{"role": "user", "content": "hi"}],
        "parameters": {"temperature": 0.0, "max_tokens": None},
        "response_text": "ok" if call_status == "success" else None,
        "status": call_status,
        "error_type": None if call_status == "success" else "provider_error",
        "error_message": None if call_status == "success" else "boom",
        "latency_ms": 10,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at

    call = LLMCall(**kwargs)
    db_session.add(call)
    db_session.commit()
    db_session.refresh(call)
    return call


def test_create_call_success(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(
        response=LLMResponse(
            provider="compatible",
            model="fake-model-2026-01",
            content="Возможен перегрев",
            latency_ms=25,
            usage=LLMUsage(prompt_tokens=5, completion_tokens=9),
        ),
    )
    _patch_provider(monkeypatch, provider)

    response = client.post("/ai/calls", json=_payload())

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["id"] > 0
    assert data["provider"] == "compatible"
    assert data["model"] == "fake-model-2026-01"
    assert data["status"] == "success"
    assert data["response_text"] == "Возможен перегрев"
    assert data["latency_ms"] == 25
    assert data["prompt_tokens"] == 5
    assert data["completion_tokens"] == 9
    assert data["prompt_version"] == "v1"
    assert data["request_messages"] == [
        {"role": "user", "content": "Почему выросла температура?"},
    ]
    assert data["parameters"] == {"temperature": 0.1, "max_tokens": 64}
    assert data["created_at"]

    assert provider.calls[0]["temperature"] == 0.1
    assert provider.calls[0]["max_tokens"] == 64
    assert provider.calls[0]["messages"] == [
        ChatMessage(role="user", content="Почему выросла температура?"),
    ]
    assert provider.closed is True

    saved = db_session.scalar(select(LLMCall))
    assert saved is not None
    assert saved.id == data["id"]


def test_create_call_timeout_returns_504_and_saves(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(
        error=LLMTimeoutError("Ollama не ответил", provider="compatible"),
    )
    _patch_provider(monkeypatch, provider)

    response = client.post("/ai/calls", json=_payload())

    assert response.status_code == 504
    detail = response.json()["detail"]
    assert detail["message"] == "Ollama не ответил"
    assert detail["call_id"] > 0

    call = db_session.get(LLMCall, detail["call_id"])
    assert call is not None
    assert call.status == "error"
    assert call.error_type == "timeout"
    assert provider.closed is True


def test_create_call_closes_provider_after_unexpected_error(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(error=RuntimeError("unexpected"))
    _patch_provider(monkeypatch, provider)

    with pytest.raises(RuntimeError, match="unexpected"):
        create_call(LLMCallCreate.model_validate(_payload()), db_session)

    assert provider.closed is True


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (LLMProviderError("boom", provider="compatible"), "provider_error"),
        (LLMResponseError("bad", provider="compatible"), "response_error"),
    ],
)
def test_create_call_provider_failure_returns_502(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_type: str,
) -> None:
    provider = FakeProvider(error=error)
    _patch_provider(monkeypatch, provider)

    response = client.post("/ai/calls", json=_payload())

    assert response.status_code == 502
    call = db_session.get(LLMCall, response.json()["detail"]["call_id"])
    assert call is not None
    assert call.error_type == expected_type
    assert provider.closed is True


def test_create_call_unknown_provider_returns_422(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/ai/calls",
        json=_payload(provider="anthropic"),
    )

    assert response.status_code == 422
    assert "Неизвестный провайдер" in response.json()["detail"]
    assert db_session.scalar(select(LLMCall)) is None


def test_create_call_unconfigured_provider_returns_500(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.ai.router.settings",
        Settings(
            _env_file=None,
            postgres_password="test",
            compatible_base_url=None,
            compatible_model=None,
        ),
    )

    response = client.post("/ai/calls", json=_payload())

    assert response.status_code == 500
    assert "COMPATIBLE_BASE_URL" in response.json()["detail"]


def test_get_call(
    client: TestClient,
    db_session: Session,
) -> None:
    call = _insert_call(db_session)

    response = client.get(f"/ai/calls/{call.id}")

    assert response.status_code == 200
    assert response.json()["id"] == call.id


def test_get_call_404(client: TestClient) -> None:
    response = client.get("/ai/calls/9999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Вызов не найден"}


def test_list_calls_orders_and_filters(
    client: TestClient,
    db_session: Session,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    first = _insert_call(
        db_session,
        provider="ollama",
        created_at=base + timedelta(minutes=1),
    )
    second = _insert_call(
        db_session,
        provider="compatible",
        created_at=base + timedelta(minutes=2),
    )
    third = _insert_call(
        db_session,
        provider="compatible",
        call_status="error",
        created_at=base + timedelta(minutes=3),
    )

    response = client.get("/ai/calls")
    assert response.status_code == 200
    assert [call["id"] for call in response.json()] == [
        third.id,
        second.id,
        first.id,
    ]

    response = client.get("/ai/calls?provider=compatible")
    assert [call["id"] for call in response.json()] == [
        third.id,
        second.id,
    ]

    response = client.get("/ai/calls?status=error")
    assert [call["id"] for call in response.json()] == [third.id]

    response = client.get("/ai/calls?limit=2&offset=1")
    assert [call["id"] for call in response.json()] == [second.id, first.id]


def test_list_calls_rejects_invalid_filters(client: TestClient) -> None:
    assert client.get("/ai/calls?status=bogus").status_code == 422
    assert client.get("/ai/calls?limit=0").status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"messages": []},
        {"temperature": 2.5},
        {"max_tokens": 0},
        {"messages": [{"role": "tool", "content": "x"}]},
        {"provider": ""},
    ],
)
def test_create_call_validation(
    client: TestClient,
    overrides: dict,
) -> None:
    response = client.post("/ai/calls", json=_payload(**overrides))

    assert response.status_code == 422
