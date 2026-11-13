"""Лексический retrieval применимых фрагментов технической документации."""

import re
from collections import Counter

from sqlalchemy import exists, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.equipment.models import Equipment
from app.knowledge.models import (
    KnowledgeDocument,
    KnowledgeDocumentApplicability,
    KnowledgeDocumentChunk,
    KnowledgeDocumentVersion,
)
from app.knowledge.schemas import KnowledgeSearchResult
from app.knowledge.service import KnowledgeEquipmentNotFoundError

_word_pattern = re.compile(r"\w+", flags=re.UNICODE)


class InvalidKnowledgeQueryError(ValueError):
    """Поисковый запрос пуст или слишком короток."""


def _base_retrieval_statement(equipment: Equipment):
    applicable = exists(
        select(KnowledgeDocumentApplicability.id).where(
            KnowledgeDocumentApplicability.document_version_id
            == KnowledgeDocumentVersion.id,
            or_(
                KnowledgeDocumentApplicability.equipment_id == equipment.id,
                KnowledgeDocumentApplicability.equipment_type
                == equipment.equipment_type,
            ),
        ),
    )
    return (
        select(
            KnowledgeDocumentChunk,
            KnowledgeDocumentVersion,
            KnowledgeDocument,
        )
        .join(
            KnowledgeDocumentVersion,
            KnowledgeDocumentVersion.id == KnowledgeDocumentChunk.document_version_id,
        )
        .join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeDocumentVersion.document_id,
        )
        .where(
            KnowledgeDocumentVersion.status == "ready",
            KnowledgeDocumentVersion.is_current.is_(True),
            applicable,
        )
    )


def _result(
    chunk: KnowledgeDocumentChunk,
    version: KnowledgeDocumentVersion,
    document: KnowledgeDocument,
    score: float,
) -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        checksum_sha256=chunk.checksum_sha256,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        score=score,
        document_id=document.id,
        document_title=document.title,
        document_type=document.document_type,
        source_name=document.source_name,
        document_version_id=version.id,
        document_version=version.version,
        source_uri=version.source_uri,
    )


def _search_postgresql(
    db: Session,
    statement,
    query: str,
    limit: int,
) -> list[KnowledgeSearchResult]:
    config = literal_column("'simple'")
    vector = func.to_tsvector(config, KnowledgeDocumentChunk.content)
    ts_query = func.websearch_to_tsquery(config, query)
    rank = func.ts_rank_cd(vector, ts_query, 32)
    rows = db.execute(
        statement.add_columns(rank.label("score"))
        .where(vector.bool_op("@@")(ts_query))
        .order_by(rank.desc(), KnowledgeDocumentChunk.id)
        .limit(limit),
    )
    return [
        _result(chunk, version, document, float(score))
        for chunk, version, document, score in rows
    ]


def _tokenize(value: str) -> list[str]:
    return _word_pattern.findall(value.casefold())


def _search_portable(
    db: Session,
    statement,
    query: str,
    limit: int,
) -> list[KnowledgeSearchResult]:
    """Детерминированный fallback для SQLite API-тестов."""
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []
    ranked: list[
        tuple[
            float,
            KnowledgeDocumentChunk,
            KnowledgeDocumentVersion,
            KnowledgeDocument,
        ]
    ] = []
    for chunk, version, document in db.execute(statement):
        tokens = _tokenize(chunk.content)
        counts = Counter(tokens)
        if not query_tokens.issubset(counts):
            continue
        score = sum(counts[token] for token in query_tokens) / max(len(tokens), 1)
        ranked.append((score, chunk, version, document))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [
        _result(chunk, version, document, score)
        for score, chunk, version, document in ranked[:limit]
    ]


def search_knowledge(
    db: Session,
    *,
    query: str,
    equipment_id: int,
    limit: int = 5,
) -> list[KnowledgeSearchResult]:
    """Ищет только готовые текущие чанки, применимые к оборудованию."""
    query = query.strip()
    if len(query) < 2:
        raise InvalidKnowledgeQueryError(
            "Поисковый запрос должен содержать минимум 2 символа",
        )
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise KnowledgeEquipmentNotFoundError
    statement = _base_retrieval_statement(equipment)
    if db.get_bind().dialect.name == "postgresql":
        return _search_postgresql(db, statement, query, limit)
    return _search_portable(db, statement, query, limit)
