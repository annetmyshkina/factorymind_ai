"""Выполнение вызовов LLM с записью в журнал."""

import time

import structlog
from sqlalchemy.orm import Session

from app.ai.contracts import ChatMessage
from app.ai.errors import LLMProviderError
from app.ai.models import LLMCall
from app.ai.providers.base import LLMProvider

logger = structlog.get_logger(__name__)


def _messages_payload(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _parameters(
    temperature: float,
    max_tokens: int | None,
) -> dict[str, object]:
    return {"temperature": temperature, "max_tokens": max_tokens}


def execute_call(
    db: Session,
    provider: LLMProvider,
    messages: list[ChatMessage],
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    prompt_version: str | None = None,
) -> LLMCall:
    """Выполняет вызов провайдера и сохраняет его в журнал.

    Ошибочные вызовы тоже сохраняются: без них нельзя оценить надёжность
    провайдера. HTTP-код по статусу вызова выбирает API-слой.
    """
    started = time.perf_counter()

    try:
        response = provider.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except LLMProviderError as exc:
        call = LLMCall(
            provider=provider.name,
            model=provider.model,
            prompt_version=prompt_version,
            request_messages=_messages_payload(messages),
            parameters=_parameters(temperature, max_tokens),
            status="error",
            error_type=exc.code,
            error_message=str(exc),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        db.add(call)
        db.commit()
        db.refresh(call)

        logger.warning(
            "llm_call_failed",
            call_id=call.id,
            provider=call.provider,
            error_type=call.error_type,
        )
        return call

    call = LLMCall(
        provider=response.provider,
        model=response.model,
        prompt_version=prompt_version,
        request_messages=_messages_payload(messages),
        parameters=_parameters(temperature, max_tokens),
        response_text=response.content,
        status="success",
        latency_ms=response.latency_ms,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    logger.info(
        "llm_call_succeeded",
        call_id=call.id,
        provider=call.provider,
        model=call.model,
        latency_ms=call.latency_ms,
    )
    return call
