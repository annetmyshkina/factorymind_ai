"""Поиск по активному подтверждённому опыту похожих инцидентов."""

import re
from collections import Counter

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session

from app.equipment.models import Equipment
from app.incidents.models import Incident, IncidentResolution
from app.incidents.schemas import SimilarIncidentResolution

_word_pattern = re.compile(r"\w+", flags=re.UNICODE)
_SAME_EQUIPMENT_BONUS = 0.1


class SimilarIncidentNotFoundError(LookupError):
    """Исходный инцидент для поиска не найден."""


class InvalidExperienceQueryError(ValueError):
    """Поисковый запрос пуст или слишком короток."""


def build_resolution_search_text(
    *,
    checks_performed: list[str],
    confirmed_cause: str | None,
    actions_taken: list[str],
    outcome: str,
) -> str:
    """Формирует стабильный индексируемый текст только из подтверждённых полей."""
    parts = [*checks_performed]
    if confirmed_cause is not None:
        parts.append(confirmed_cause)
    parts.extend(actions_taken)
    parts.append(outcome)
    return "\n".join(parts)


def _base_statement(source_incident: Incident, source_equipment: Equipment):
    return (
        select(IncidentResolution, Incident, Equipment)
        .join(Incident, Incident.id == IncidentResolution.incident_id)
        .join(Equipment, Equipment.id == Incident.equipment_id)
        .where(
            IncidentResolution.is_active.is_(True),
            IncidentResolution.incident_id != source_incident.id,
            Equipment.equipment_type == source_equipment.equipment_type,
        )
    )


def _result(
    resolution: IncidentResolution,
    incident: Incident,
    equipment: Equipment,
    *,
    source_equipment_id: int,
    score: float,
) -> SimilarIncidentResolution:
    return SimilarIncidentResolution(
        resolution_id=resolution.id,
        resolution_revision=resolution.revision,
        incident_id=incident.id,
        incident_title=incident.title,
        equipment_id=equipment.id,
        equipment_code=equipment.code,
        equipment_type=equipment.equipment_type,
        match_scope=(
            "same_equipment"
            if equipment.id == source_equipment_id
            else "same_equipment_type"
        ),
        checks_performed=list(resolution.checks_performed),
        confirmed_cause=resolution.confirmed_cause,
        actions_taken=list(resolution.actions_taken),
        outcome=resolution.outcome,
        confirmed_at=resolution.confirmed_at,
        score=score,
        citation=f"EXP:R{resolution.id}:V{resolution.revision}",
    )


def _search_postgresql(
    db: Session,
    statement,
    query: str,
    *,
    source_equipment_id: int,
    limit: int,
) -> list[SimilarIncidentResolution]:
    config = literal_column("'simple'")
    vector = func.to_tsvector(config, IncidentResolution.search_text)
    ts_query = func.websearch_to_tsquery(config, query)
    text_rank = func.ts_rank_cd(vector, ts_query, 32)
    score = text_rank + case(
        (Equipment.id == source_equipment_id, _SAME_EQUIPMENT_BONUS),
        else_=0.0,
    )
    rows = db.execute(
        statement.add_columns(score.label("score"))
        .where(vector.bool_op("@@")(ts_query))
        .order_by(score.desc(), IncidentResolution.id)
        .limit(limit),
    )
    return [
        _result(
            resolution,
            incident,
            equipment,
            source_equipment_id=source_equipment_id,
            score=float(result_score),
        )
        for resolution, incident, equipment, result_score in rows
    ]


def _tokenize(value: str) -> list[str]:
    return _word_pattern.findall(value.casefold())


def _search_portable(
    db: Session,
    statement,
    query: str,
    *,
    source_equipment_id: int,
    limit: int,
) -> list[SimilarIncidentResolution]:
    """Детерминированный fallback для SQLite API-тестов."""
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []
    ranked: list[tuple[float, IncidentResolution, Incident, Equipment]] = []
    for resolution, incident, equipment in db.execute(statement):
        tokens = _tokenize(resolution.search_text)
        counts = Counter(tokens)
        if not query_tokens.issubset(counts):
            continue
        score = sum(counts[token] for token in query_tokens) / max(len(tokens), 1)
        if equipment.id == source_equipment_id:
            score += _SAME_EQUIPMENT_BONUS
        ranked.append((score, resolution, incident, equipment))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [
        _result(
            resolution,
            incident,
            equipment,
            source_equipment_id=source_equipment_id,
            score=score,
        )
        for score, resolution, incident, equipment in ranked[:limit]
    ]


def search_similar_incidents(
    db: Session,
    *,
    incident_id: int,
    query: str,
    limit: int = 5,
) -> list[SimilarIncidentResolution]:
    """Ищет опыт того же типа оборудования, исключая исходный инцидент."""
    query = query.strip()
    if len(query) < 2:
        raise InvalidExperienceQueryError(
            "Поисковый запрос должен содержать минимум 2 символа",
        )
    source_incident = db.get(Incident, incident_id)
    if source_incident is None:
        raise SimilarIncidentNotFoundError
    source_equipment = db.get(Equipment, source_incident.equipment_id)
    if source_equipment is None:
        raise SimilarIncidentNotFoundError

    statement = _base_statement(source_incident, source_equipment)
    if db.get_bind().dialect.name == "postgresql":
        return _search_postgresql(
            db,
            statement,
            query,
            source_equipment_id=source_equipment.id,
            limit=limit,
        )
    return _search_portable(
        db,
        statement,
        query,
        source_equipment_id=source_equipment.id,
        limit=limit,
    )
