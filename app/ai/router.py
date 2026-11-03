"""API вызова моделей и журнала вызовов."""

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.contracts import ChatMessage
from app.ai.errors import ProviderNotConfiguredError, UnknownProviderError
from app.ai.models import LLMCall, PromptVersion
from app.ai.providers import build_provider
from app.ai.schemas import (
    LLMCallCreate,
    LLMCallResponse,
    PromptVersionCreate,
    PromptVersionResponse,
)
from app.ai.service import execute_call
from app.core.config import settings
from app.core.database import get_db

router = APIRouter(prefix="/ai", tags=["AI"])

logger = structlog.get_logger(__name__)


@router.post(
    "/calls",
    response_model=LLMCallResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_call(
    payload: LLMCallCreate,
    db: Session = Depends(get_db),
) -> LLMCallResponse:
    """Вызывает модель и сохраняет вызов в журнал."""
    try:
        provider = build_provider(
            payload.provider,
            settings,
            model=payload.model,
        )
    except UnknownProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    messages = [
        ChatMessage(role=message.role, content=message.content)
        for message in payload.messages
    ]

    call = execute_call(
        db,
        provider,
        messages,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        prompt_version=payload.prompt_version,
    )

    if call.status == "error":
        status_code = (
            status.HTTP_504_GATEWAY_TIMEOUT
            if call.error_type == "timeout"
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail={"message": call.error_message, "call_id": call.id},
        )

    return call


@router.get("/calls", response_model=list[LLMCallResponse])
def list_calls(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    provider: str | None = None,
    status_filter: Annotated[
        Literal["success", "error"] | None,
        Query(alias="status"),
    ] = None,
    db: Session = Depends(get_db),
) -> list[LLMCallResponse]:
    """Возвращает журнал вызовов, сначала новые."""
    query = select(LLMCall).order_by(
        LLMCall.created_at.desc(),
        LLMCall.id.desc(),
    )
    if provider is not None:
        query = query.where(LLMCall.provider == provider)
    if status_filter is not None:
        query = query.where(LLMCall.status == status_filter)

    query = query.offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.get("/calls/{call_id}", response_model=LLMCallResponse)
def get_call(
    call_id: int,
    db: Session = Depends(get_db),
) -> LLMCallResponse:
    """Возвращает один вызов из журнала."""
    call = db.get(LLMCall, call_id)
    if call is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вызов не найден",
        )
    return call


@router.post(
    "/prompts",
    response_model=PromptVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_prompt_version(
    payload: PromptVersionCreate,
    db: Session = Depends(get_db),
) -> PromptVersionResponse:
    """Создаёт неизменяемую версию промпта."""
    prompt = PromptVersion(
        name=payload.name,
        version=payload.version,
        content=payload.content,
    )
    db.add(prompt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Версия промпта уже существует",
        ) from None

    db.refresh(prompt)
    return prompt


@router.get("/prompts", response_model=list[PromptVersionResponse])
def list_prompt_versions(
    name: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[PromptVersionResponse]:
    """Возвращает версии промптов."""
    query = select(PromptVersion).order_by(
        PromptVersion.name,
        PromptVersion.id,
    )
    if name is not None:
        query = query.where(PromptVersion.name == name)

    query = query.offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.get("/prompts/{prompt_id}", response_model=PromptVersionResponse)
def get_prompt_version(
    prompt_id: int,
    db: Session = Depends(get_db),
) -> PromptVersionResponse:
    """Возвращает одну версию промпта."""
    prompt = db.get(PromptVersion, prompt_id)
    if prompt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Версия промпта не найдена",
        )
    return prompt
