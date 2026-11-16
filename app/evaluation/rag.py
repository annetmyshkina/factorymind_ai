"""Воспроизводимая оценка retrieval без LLM-судьи."""

import json
from pathlib import Path
from statistics import fmean
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.equipment.models import Equipment
from app.evaluation.errors import BenchmarkError
from app.incidents.experience import search_similar_incidents
from app.incidents.models import Incident
from app.knowledge.retrieval import search_knowledge

RAG_RETRIEVAL_EVALUATOR_VERSION = "rag-retrieval-deterministic-v1"


class ExpectedDocumentSource(BaseModel):
    """Стабильная ссылка на ожидаемый фрагмент документа."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_title: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)

    @property
    def key(self) -> str:
        return document_source_key(
            self.document_title,
            self.document_version,
            self.chunk_index,
        )


class ExpectedExperienceSource(BaseModel):
    """Стабильная ссылка на ревизию подтверждённого решения."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    equipment_code: str = Field(min_length=1)
    incident_title: str = Field(min_length=1)
    revision: int = Field(gt=0)

    @property
    def key(self) -> str:
        return experience_source_key(
            self.equipment_code,
            self.incident_title,
            self.revision,
        )


class RAGBenchmarkCase(BaseModel):
    """Один запрос с исчерпывающей разметкой ожидаемых источников."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    equipment_code: str = Field(min_length=1)
    incident_title: str = Field(min_length=1)
    query: str = Field(min_length=2, max_length=500)
    document_k: int = Field(default=5, ge=1, le=20)
    experience_k: int = Field(default=3, ge=1, le=20)
    expected_documents: list[ExpectedDocumentSource] = Field(default_factory=list)
    expected_experiences: list[ExpectedExperienceSource] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def expected_sources_are_unique(self) -> Self:
        document_keys = [source.key for source in self.expected_documents]
        experience_keys = [source.key for source in self.expected_experiences]
        if len(document_keys) != len(set(document_keys)):
            raise ValueError("Ожидаемые документы не должны повторяться")
        if len(experience_keys) != len(set(experience_keys)):
            raise ValueError("Ожидаемые решения не должны повторяться")
        return self


class RAGBenchmarkSuite(BaseModel):
    """Версионированный набор retrieval-кейсов."""

    model_config = ConfigDict(extra="forbid")

    suite_version: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    cases: list[RAGBenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id не должны повторяться")
        return self


class RankedRetrievalMetrics(BaseModel):
    """Независимые метрики одного ранжированного списка."""

    k: int = Field(gt=0)
    expected_count: int = Field(ge=0)
    retrieved_count: int = Field(ge=0)
    relevant_retrieved_count: int = Field(ge=0)
    hit_at_k: bool | None
    precision_at_k: float | None = Field(default=None, ge=0, le=1)
    recall_at_k: float | None = Field(default=None, ge=0, le=1)
    reciprocal_rank: float | None = Field(default=None, ge=0, le=1)
    exclusion_pass: bool | None
    expected_keys: list[str]
    retrieved_keys: list[str]

    @model_validator(mode="after")
    def metric_state_is_consistent(self) -> Self:
        ranked_values = (
            self.hit_at_k,
            self.precision_at_k,
            self.recall_at_k,
            self.reciprocal_rank,
        )
        if self.retrieved_count > self.k:
            raise ValueError("retrieved_count не может превышать k")
        if self.relevant_retrieved_count > min(
            self.expected_count,
            self.retrieved_count,
        ):
            raise ValueError("Число релевантных результатов некорректно")
        if self.expected_count > 0:
            if any(value is None for value in ranked_values):
                raise ValueError("Retrieval-метрики обязательны для размеченного кейса")
            if self.exclusion_pass is not None:
                raise ValueError("exclusion_pass неприменим к размеченному кейсу")
        elif any(value is not None for value in ranked_values):
            raise ValueError("Retrieval-метрики неприменимы к exclusion-кейсу")
        elif self.exclusion_pass is None:
            raise ValueError("exclusion_pass обязателен для exclusion-кейса")
        return self


class RAGBenchmarkCaseReport(BaseModel):
    """Раздельный результат retrieval документации и опыта."""

    case_id: str
    documents: RankedRetrievalMetrics
    experiences: RankedRetrievalMetrics


class RetrievalMetricSummary(BaseModel):
    """Сводка одного retrieval-канала без объединения разных метрик."""

    relevant_cases: int = Field(ge=0)
    exclusion_cases: int = Field(ge=0)
    hit_rate: float | None = Field(default=None, ge=0, le=1)
    mean_precision_at_k: float | None = Field(default=None, ge=0, le=1)
    mean_recall_at_k: float | None = Field(default=None, ge=0, le=1)
    mean_reciprocal_rank: float | None = Field(default=None, ge=0, le=1)
    exclusion_pass_rate: float | None = Field(default=None, ge=0, le=1)


class RAGBenchmarkReport(BaseModel):
    """Отчёт suite с независимыми сводками по двум типам источников."""

    suite_version: str
    evaluator_version: str
    cases: list[RAGBenchmarkCaseReport]
    document_summary: RetrievalMetricSummary
    experience_summary: RetrievalMetricSummary


def document_source_key(title: str, version: str, chunk_index: int) -> str:
    """Создаёт стабильный ключ документа, независимый от ID конкретной БД."""
    return f"document:{title}:version:{version}:chunk:{chunk_index}"


def experience_source_key(
    equipment_code: str,
    incident_title: str,
    revision: int,
) -> str:
    """Создаёт стабильный ключ подтверждённого опыта для benchmark-корпуса."""
    return f"experience:{equipment_code}:incident:{incident_title}:revision:{revision}"


def evaluate_ranked_retrieval(
    retrieved_keys: list[str],
    expected_keys: list[str],
    *,
    k: int,
) -> RankedRetrievalMetrics:
    """Считает метрики top-k либо отдельную проверку корректного исключения."""
    if len(retrieved_keys) != len(set(retrieved_keys)):
        raise BenchmarkError("Результаты retrieval не должны повторяться")
    if len(expected_keys) != len(set(expected_keys)):
        raise BenchmarkError("Ожидаемые источники не должны повторяться")

    top_k = retrieved_keys[:k]
    expected = set(expected_keys)
    relevant_positions = [
        position
        for position, source_key in enumerate(top_k, start=1)
        if source_key in expected
    ]
    relevant_count = len(relevant_positions)

    if not expected_keys:
        return RankedRetrievalMetrics(
            k=k,
            expected_count=0,
            retrieved_count=len(top_k),
            relevant_retrieved_count=0,
            hit_at_k=None,
            precision_at_k=None,
            recall_at_k=None,
            reciprocal_rank=None,
            exclusion_pass=not top_k,
            expected_keys=[],
            retrieved_keys=top_k,
        )

    return RankedRetrievalMetrics(
        k=k,
        expected_count=len(expected_keys),
        retrieved_count=len(top_k),
        relevant_retrieved_count=relevant_count,
        hit_at_k=bool(relevant_positions),
        precision_at_k=relevant_count / k,
        recall_at_k=relevant_count / len(expected_keys),
        reciprocal_rank=(1 / relevant_positions[0] if relevant_positions else 0.0),
        exclusion_pass=None,
        expected_keys=expected_keys,
        retrieved_keys=top_k,
    )


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def summarize_retrieval(
    metrics: list[RankedRetrievalMetrics],
) -> RetrievalMetricSummary:
    """Агрегирует одноимённые метрики, не создавая общего score."""
    relevant = [item for item in metrics if item.expected_count > 0]
    exclusions = [item for item in metrics if item.expected_count == 0]
    return RetrievalMetricSummary(
        relevant_cases=len(relevant),
        exclusion_cases=len(exclusions),
        hit_rate=_mean([float(item.hit_at_k) for item in relevant]),
        mean_precision_at_k=_mean(
            [float(item.precision_at_k) for item in relevant],
        ),
        mean_recall_at_k=_mean([float(item.recall_at_k) for item in relevant]),
        mean_reciprocal_rank=_mean(
            [float(item.reciprocal_rank) for item in relevant],
        ),
        exclusion_pass_rate=_mean(
            [float(item.exclusion_pass) for item in exclusions],
        ),
    )


def load_rag_benchmark(path: Path) -> RAGBenchmarkSuite:
    """Загружает и строго валидирует versioned JSON-suite."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"Не удалось прочитать benchmark: {path}") from exc
    try:
        return RAGBenchmarkSuite.model_validate(payload)
    except ValidationError as exc:
        raise BenchmarkError(f"Benchmark не прошёл валидацию: {path}") from exc


def _resolve_case_context(
    db: Session,
    case: RAGBenchmarkCase,
) -> tuple[Equipment, Incident]:
    equipment = db.scalar(
        select(Equipment).where(Equipment.code == case.equipment_code),
    )
    if equipment is None:
        raise BenchmarkError(
            f"Кейс {case.case_id}: оборудование {case.equipment_code} не найдено",
        )
    incidents = list(
        db.scalars(
            select(Incident).where(
                Incident.equipment_id == equipment.id,
                Incident.title == case.incident_title,
            ),
        ),
    )
    if len(incidents) != 1:
        raise BenchmarkError(
            f"Кейс {case.case_id}: ожидается ровно один исходный инцидент",
        )
    return equipment, incidents[0]


def evaluate_rag_case(
    db: Session,
    case: RAGBenchmarkCase,
) -> RAGBenchmarkCaseReport:
    """Выполняет оба retrieval-контура и сопоставляет стабильные source keys."""
    equipment, incident = _resolve_case_context(db, case)
    documents = search_knowledge(
        db,
        query=case.query,
        equipment_id=equipment.id,
        limit=case.document_k,
    )
    experiences = search_similar_incidents(
        db,
        incident_id=incident.id,
        query=case.query,
        limit=case.experience_k,
    )

    document_metrics = evaluate_ranked_retrieval(
        [
            document_source_key(
                item.document_title,
                item.document_version,
                item.chunk_index,
            )
            for item in documents
        ],
        [item.key for item in case.expected_documents],
        k=case.document_k,
    )
    experience_metrics = evaluate_ranked_retrieval(
        [
            experience_source_key(
                item.equipment_code,
                item.incident_title,
                item.resolution_revision,
            )
            for item in experiences
        ],
        [item.key for item in case.expected_experiences],
        k=case.experience_k,
    )
    return RAGBenchmarkCaseReport(
        case_id=case.case_id,
        documents=document_metrics,
        experiences=experience_metrics,
    )


def evaluate_rag_suite(
    db: Session,
    suite: RAGBenchmarkSuite,
) -> RAGBenchmarkReport:
    """Формирует воспроизводимый отчёт без единого агрегированного балла."""
    case_reports = [evaluate_rag_case(db, case) for case in suite.cases]
    return RAGBenchmarkReport(
        suite_version=suite.suite_version,
        evaluator_version=RAG_RETRIEVAL_EVALUATOR_VERSION,
        cases=case_reports,
        document_summary=summarize_retrieval(
            [report.documents for report in case_reports],
        ),
        experience_summary=summarize_retrieval(
            [report.experiences for report in case_reports],
        ),
    )
