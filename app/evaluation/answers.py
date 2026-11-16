"""Детерминированная оценка структурированных ответов incident analysis."""

import json
from pathlib import Path
from statistics import fmean
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from app.evaluation.errors import BenchmarkError
from app.incidents.schemas import IncidentAnalysisResult

SourceId = Annotated[int, Field(gt=0)]
InsufficientDataExpectation = Literal["required", "forbidden", "optional"]
_CONCLUSION_FIELDS = ("possible_causes", "required_checks", "recommendations")
ANSWER_EVALUATOR_VERSION = "incident-answer-deterministic-v1"


class AnswerBenchmarkCase(BaseModel):
    """Один сырой ответ и ожидаемые свойства его проверяемой структуры."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    response_text: str = Field(min_length=1)
    allowed_chunk_ids: list[SourceId] = Field(default_factory=list)
    allowed_resolution_ids: list[SourceId] = Field(default_factory=list)
    expected_chunk_ids: list[SourceId] = Field(default_factory=list)
    expected_resolution_ids: list[SourceId] = Field(default_factory=list)
    insufficient_data: InsufficientDataExpectation = "optional"
    required_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def source_expectations_are_consistent(self) -> Self:
        source_lists = (
            self.allowed_chunk_ids,
            self.allowed_resolution_ids,
            self.expected_chunk_ids,
            self.expected_resolution_ids,
        )
        if any(len(values) != len(set(values)) for values in source_lists):
            raise ValueError("Идентификаторы источников не должны повторяться")
        if not set(self.expected_chunk_ids).issubset(self.allowed_chunk_ids):
            raise ValueError("Ожидаемые chunk_id должны входить в allowed_chunk_ids")
        if not set(self.expected_resolution_ids).issubset(
            self.allowed_resolution_ids,
        ):
            raise ValueError(
                "Ожидаемые resolution_id должны входить в allowed_resolution_ids",
            )
        if len(self.required_warnings) != len(set(self.required_warnings)):
            raise ValueError("Обязательные предупреждения не должны повторяться")
        return self


class AnswerBenchmarkSuite(BaseModel):
    """Версионированный набор записанных ответов моделей."""

    model_config = ConfigDict(extra="forbid")

    suite_version: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    cases: list[AnswerBenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id не должны повторяться")
        return self


class AnswerCaseReport(BaseModel):
    """Независимые критерии качества одного записанного ответа."""

    case_id: str
    json_valid: bool
    schema_valid: bool
    conclusion_count: int | None = Field(default=None, ge=0)
    citation_coverage: float | None = Field(default=None, ge=0, le=1)
    citations_valid: bool | None
    unknown_chunk_ids: list[int] | None
    unknown_resolution_ids: list[int] | None
    expected_document_recall: float | None = Field(default=None, ge=0, le=1)
    expected_experience_recall: float | None = Field(default=None, ge=0, le=1)
    insufficient_data_pass: bool | None
    required_warnings_pass: bool | None
    validation_errors: list[str]


class AnswerMetricSummary(BaseModel):
    """Сводка независимых критериев без общего score."""

    case_count: int = Field(ge=0)
    json_valid_rate: float | None = Field(default=None, ge=0, le=1)
    schema_valid_rate: float | None = Field(default=None, ge=0, le=1)
    mean_citation_coverage: float | None = Field(default=None, ge=0, le=1)
    citation_valid_rate: float | None = Field(default=None, ge=0, le=1)
    mean_expected_document_recall: float | None = Field(default=None, ge=0, le=1)
    mean_expected_experience_recall: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    insufficient_data_pass_rate: float | None = Field(default=None, ge=0, le=1)
    required_warnings_pass_rate: float | None = Field(default=None, ge=0, le=1)


class AnswerBenchmarkReport(BaseModel):
    """Отчёт versioned suite записанных ответов."""

    suite_version: str
    prompt_version: str
    evaluator_version: str
    cases: list[AnswerCaseReport]
    summary: AnswerMetricSummary


def load_answer_benchmark(path: Path) -> AnswerBenchmarkSuite:
    """Загружает JSON-suite и проверяет согласованность source expectations."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"Не удалось прочитать benchmark: {path}") from exc
    try:
        return AnswerBenchmarkSuite.model_validate(payload)
    except ValidationError as exc:
        raise BenchmarkError(f"Benchmark не прошёл валидацию: {path}") from exc


def _raw_citation_coverage(payload: object) -> tuple[int | None, float | None]:
    """Диагностирует покрытие даже у ответа, не прошедшего полную схему."""
    if not isinstance(payload, dict):
        return None, None
    items: list[object] = []
    for field in _CONCLUSION_FIELDS:
        field_items = payload.get(field)
        if not isinstance(field_items, list):
            return None, None
        items.extend(field_items)
    if not items:
        return 0, None

    covered = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        chunk_ids = item.get("source_chunk_ids", [])
        resolution_ids = item.get("resolution_ids", [])
        if (
            isinstance(chunk_ids, list)
            and isinstance(resolution_ids, list)
            and (chunk_ids or resolution_ids)
        ):
            covered += 1
    return len(items), covered / len(items)


def _validation_errors(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors(include_url=False)
    ]


def _recall(cited: set[int], expected: list[int]) -> float | None:
    if not expected:
        return None
    return len(cited.intersection(expected)) / len(expected)


def evaluate_answer_case(case: AnswerBenchmarkCase) -> AnswerCaseReport:
    """Оценивает только проверяемые свойства ответа, не его скрытый смысл."""
    try:
        payload = json.loads(case.response_text)
    except json.JSONDecodeError as exc:
        return AnswerCaseReport(
            case_id=case.case_id,
            json_valid=False,
            schema_valid=False,
            citations_valid=None,
            unknown_chunk_ids=None,
            unknown_resolution_ids=None,
            insufficient_data_pass=None,
            required_warnings_pass=None,
            validation_errors=[f"JSON: {exc.msg}"],
        )

    conclusion_count, citation_coverage = _raw_citation_coverage(payload)
    try:
        result = IncidentAnalysisResult.model_validate(payload)
    except ValidationError as exc:
        return AnswerCaseReport(
            case_id=case.case_id,
            json_valid=True,
            schema_valid=False,
            conclusion_count=conclusion_count,
            citation_coverage=citation_coverage,
            citations_valid=None,
            unknown_chunk_ids=None,
            unknown_resolution_ids=None,
            insufficient_data_pass=None,
            required_warnings_pass=None,
            validation_errors=_validation_errors(exc),
        )

    cited_items = (
        result.possible_causes + result.required_checks + result.recommendations
    )
    cited_chunks = {
        chunk_id for item in cited_items for chunk_id in item.source_chunk_ids
    }
    cited_resolutions = {
        resolution_id for item in cited_items for resolution_id in item.resolution_ids
    }
    unknown_chunks = sorted(cited_chunks - set(case.allowed_chunk_ids))
    unknown_resolutions = sorted(
        cited_resolutions - set(case.allowed_resolution_ids),
    )

    if case.insufficient_data == "required":
        insufficient_data_pass = bool(result.insufficient_data)
    elif case.insufficient_data == "forbidden":
        insufficient_data_pass = not result.insufficient_data
    else:
        insufficient_data_pass = None

    required_warnings_pass = (
        all(warning in result.warnings for warning in case.required_warnings)
        if case.required_warnings
        else None
    )
    return AnswerCaseReport(
        case_id=case.case_id,
        json_valid=True,
        schema_valid=True,
        conclusion_count=conclusion_count,
        citation_coverage=citation_coverage,
        citations_valid=not unknown_chunks and not unknown_resolutions,
        unknown_chunk_ids=unknown_chunks,
        unknown_resolution_ids=unknown_resolutions,
        expected_document_recall=_recall(cited_chunks, case.expected_chunk_ids),
        expected_experience_recall=_recall(
            cited_resolutions,
            case.expected_resolution_ids,
        ),
        insufficient_data_pass=insufficient_data_pass,
        required_warnings_pass=required_warnings_pass,
        validation_errors=[],
    )


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _rate(values: list[bool]) -> float | None:
    return _mean([float(value) for value in values])


def summarize_answer_cases(cases: list[AnswerCaseReport]) -> AnswerMetricSummary:
    """Агрегирует каждый критерий отдельно, сохраняя неприменимые как null."""
    return AnswerMetricSummary(
        case_count=len(cases),
        json_valid_rate=_rate([case.json_valid for case in cases]),
        schema_valid_rate=_rate([case.schema_valid for case in cases]),
        mean_citation_coverage=_mean(
            [
                case.citation_coverage
                for case in cases
                if case.citation_coverage is not None
            ],
        ),
        citation_valid_rate=_rate(
            [
                case.citations_valid
                for case in cases
                if case.citations_valid is not None
            ],
        ),
        mean_expected_document_recall=_mean(
            [
                case.expected_document_recall
                for case in cases
                if case.expected_document_recall is not None
            ],
        ),
        mean_expected_experience_recall=_mean(
            [
                case.expected_experience_recall
                for case in cases
                if case.expected_experience_recall is not None
            ],
        ),
        insufficient_data_pass_rate=_rate(
            [
                case.insufficient_data_pass
                for case in cases
                if case.insufficient_data_pass is not None
            ],
        ),
        required_warnings_pass_rate=_rate(
            [
                case.required_warnings_pass
                for case in cases
                if case.required_warnings_pass is not None
            ],
        ),
    )


def evaluate_answer_suite(suite: AnswerBenchmarkSuite) -> AnswerBenchmarkReport:
    """Оценивает записанные ответы без БД, сети и LLM-судьи."""
    case_reports = [evaluate_answer_case(case) for case in suite.cases]
    return AnswerBenchmarkReport(
        suite_version=suite.suite_version,
        prompt_version=suite.prompt_version,
        evaluator_version=ANSWER_EVALUATOR_VERSION,
        cases=case_reports,
        summary=summarize_answer_cases(case_reports),
    )
