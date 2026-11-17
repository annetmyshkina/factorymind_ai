"""Read-only эксплуатационные метрики сохранённых AI-анализов инцидентов."""

from collections import Counter
from datetime import UTC, datetime

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import LLMCall
from app.incidents.models import (
    IncidentAnalysis,
    IncidentAnalysisFeedback,
    IncidentResolution,
    IncidentResolutionEvent,
)

OPERATIONAL_METRICS_VERSION = "incident-operational-v1"
INTERPRETATION_WARNINGS = [
    "Feedback является субъективной оценкой, а не доказательством корректности.",
    "Actor не проверен: это пользовательская метка до внедрения аутентификации.",
    "Связь с подтверждённым решением является эксплуатационным сигналом, "
    "а не общей оценкой модели.",
]


class OperationalMetricFilters(BaseModel):
    """Фильтры когорты по времени создания и фактической модели анализа."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str | None = Field(default=None, min_length=1, max_length=50)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    prompt_version: str | None = Field(default=None, min_length=1, max_length=50)
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None

    @field_validator("created_from", "created_to")
    @classmethod
    def normalize_to_utc(
        cls,
        value: AwareDatetime | None,
    ) -> AwareDatetime | None:
        return value.astimezone(UTC) if value is not None else None


class AnalysisCohortMetrics(BaseModel):
    """Размер и состав выбранной когорты анализов."""

    analysis_count: int = Field(ge=0)
    incident_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    insufficient_count: int = Field(ge=0)
    analyses_with_feedback: int = Field(ge=0)
    feedback_coverage_rate: float | None = Field(default=None, ge=0, le=1)


class FeedbackOperationalMetrics(BaseModel):
    """Entry-based распределение субъективных отзывов."""

    entry_count: int = Field(ge=0)
    helpful_count: int = Field(ge=0)
    unhelpful_count: int = Field(ge=0)
    incorrect_count: int = Field(ge=0)
    helpful_rate: float | None = Field(default=None, ge=0, le=1)
    unhelpful_rate: float | None = Field(default=None, ge=0, le=1)
    incorrect_rate: float | None = Field(default=None, ge=0, le=1)


class ResolutionOperationalMetrics(BaseModel):
    """Связь когорты с подтверждениями и аудитом их изменений."""

    resolution_count: int = Field(ge=0)
    active_resolution_count: int = Field(ge=0)
    currently_revoked_resolution_count: int = Field(ge=0)
    linked_to_selected_analysis_count: int = Field(ge=0)
    resolution_analysis_link_rate: float | None = Field(default=None, ge=0, le=1)
    analyses_with_active_resolution: int = Field(ge=0)
    active_resolution_analysis_rate: float | None = Field(default=None, ge=0, le=1)
    corrected_resolution_count: int = Field(ge=0)
    corrected_resolution_rate: float | None = Field(default=None, ge=0, le=1)
    ever_revoked_resolution_count: int = Field(ge=0)
    ever_revoked_resolution_rate: float | None = Field(default=None, ge=0, le=1)
    reconfirmed_resolution_count: int = Field(ge=0)
    reconfirmed_resolution_rate: float | None = Field(default=None, ge=0, le=1)
    confirmed_event_count: int = Field(ge=0)
    corrected_event_count: int = Field(ge=0)
    revoked_event_count: int = Field(ge=0)


class IncidentAnalysisOperationalReport(BaseModel):
    """Версионированный отчёт эксплуатационных сигналов без quality score."""

    metrics_version: str
    generated_at: AwareDatetime
    filters: OperationalMetricFilters
    cohort: AnalysisCohortMetrics
    feedback: FeedbackOperationalMetrics
    resolutions: ResolutionOperationalMetrics
    interpretation_warnings: list[str]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _selected_analyses(
    db: Session,
    filters: OperationalMetricFilters,
) -> list[tuple[int, int, str]]:
    statement = (
        select(
            IncidentAnalysis.id,
            IncidentAnalysis.incident_id,
            IncidentAnalysis.status,
        )
        .outerjoin(LLMCall, LLMCall.id == IncidentAnalysis.llm_call_id)
        .order_by(IncidentAnalysis.id)
    )
    if filters.provider is not None:
        statement = statement.where(LLMCall.provider == filters.provider)
    if filters.model is not None:
        statement = statement.where(LLMCall.model == filters.model)
    if filters.prompt_version is not None:
        statement = statement.where(
            IncidentAnalysis.prompt_version == filters.prompt_version,
        )
    if filters.created_from is not None:
        statement = statement.where(
            IncidentAnalysis.created_at >= filters.created_from,
        )
    if filters.created_to is not None:
        statement = statement.where(
            IncidentAnalysis.created_at <= filters.created_to,
        )
    return [(row.id, row.incident_id, row.status) for row in db.execute(statement)]


def _feedback_metrics(
    db: Session,
    analysis_ids: list[int],
) -> tuple[FeedbackOperationalMetrics, int]:
    if not analysis_ids:
        return FeedbackOperationalMetrics(
            entry_count=0,
            helpful_count=0,
            unhelpful_count=0,
            incorrect_count=0,
        ), 0
    rows = list(
        db.execute(
            select(
                IncidentAnalysisFeedback.analysis_id,
                IncidentAnalysisFeedback.rating,
            ).where(IncidentAnalysisFeedback.analysis_id.in_(analysis_ids)),
        ),
    )
    ratings = Counter(row.rating for row in rows)
    entry_count = len(rows)
    return FeedbackOperationalMetrics(
        entry_count=entry_count,
        helpful_count=ratings["helpful"],
        unhelpful_count=ratings["unhelpful"],
        incorrect_count=ratings["incorrect"],
        helpful_rate=_rate(ratings["helpful"], entry_count),
        unhelpful_rate=_rate(ratings["unhelpful"], entry_count),
        incorrect_rate=_rate(ratings["incorrect"], entry_count),
    ), len({row.analysis_id for row in rows})


def _resolution_metrics(
    db: Session,
    *,
    analysis_ids: list[int],
    incident_ids: list[int],
) -> ResolutionOperationalMetrics:
    if not incident_ids:
        return ResolutionOperationalMetrics(
            resolution_count=0,
            active_resolution_count=0,
            currently_revoked_resolution_count=0,
            linked_to_selected_analysis_count=0,
            analyses_with_active_resolution=0,
            corrected_resolution_count=0,
            ever_revoked_resolution_count=0,
            reconfirmed_resolution_count=0,
            confirmed_event_count=0,
            corrected_event_count=0,
            revoked_event_count=0,
        )
    resolutions = list(
        db.scalars(
            select(IncidentResolution).where(
                IncidentResolution.incident_id.in_(incident_ids),
            ),
        ),
    )
    resolution_ids = [resolution.id for resolution in resolutions]
    events = (
        list(
            db.execute(
                select(
                    IncidentResolutionEvent.resolution_id,
                    IncidentResolutionEvent.event_type,
                ).where(
                    IncidentResolutionEvent.resolution_id.in_(resolution_ids),
                ),
            ),
        )
        if resolution_ids
        else []
    )
    event_counts = Counter(row.event_type for row in events)
    events_by_resolution: dict[int, Counter[str]] = {
        resolution_id: Counter() for resolution_id in resolution_ids
    }
    for event in events:
        events_by_resolution[event.resolution_id][event.event_type] += 1

    selected_analysis_ids = set(analysis_ids)
    linked = [
        resolution
        for resolution in resolutions
        if resolution.analysis_id in selected_analysis_ids
    ]
    active_linked_analysis_ids = {
        resolution.analysis_id
        for resolution in linked
        if resolution.is_active and resolution.analysis_id is not None
    }
    resolution_count = len(resolutions)
    corrected_count = sum(
        events_by_resolution[item.id]["corrected"] > 0 for item in resolutions
    )
    ever_revoked_count = sum(
        events_by_resolution[item.id]["revoked"] > 0 for item in resolutions
    )
    reconfirmed_count = sum(
        events_by_resolution[item.id]["confirmed"] > 1 for item in resolutions
    )
    return ResolutionOperationalMetrics(
        resolution_count=resolution_count,
        active_resolution_count=sum(item.is_active for item in resolutions),
        currently_revoked_resolution_count=sum(
            not item.is_active for item in resolutions
        ),
        linked_to_selected_analysis_count=len(linked),
        resolution_analysis_link_rate=_rate(len(linked), resolution_count),
        analyses_with_active_resolution=len(active_linked_analysis_ids),
        active_resolution_analysis_rate=_rate(
            len(active_linked_analysis_ids),
            len(analysis_ids),
        ),
        corrected_resolution_count=corrected_count,
        corrected_resolution_rate=_rate(corrected_count, resolution_count),
        ever_revoked_resolution_count=ever_revoked_count,
        ever_revoked_resolution_rate=_rate(ever_revoked_count, resolution_count),
        reconfirmed_resolution_count=reconfirmed_count,
        reconfirmed_resolution_rate=_rate(reconfirmed_count, resolution_count),
        confirmed_event_count=event_counts["confirmed"],
        corrected_event_count=event_counts["corrected"],
        revoked_event_count=event_counts["revoked"],
    )


def build_incident_analysis_operational_report(
    db: Session,
    filters: OperationalMetricFilters,
) -> IncidentAnalysisOperationalReport:
    """Строит read-only отчёт по когорте анализов и связанным инцидентам."""
    analyses = _selected_analyses(db, filters)
    analysis_ids = [analysis_id for analysis_id, _, _ in analyses]
    incident_ids = list({incident_id for _, incident_id, _ in analyses})
    feedback, analyses_with_feedback = _feedback_metrics(db, analysis_ids)
    analysis_count = len(analyses)
    cohort = AnalysisCohortMetrics(
        analysis_count=analysis_count,
        incident_count=len(incident_ids),
        completed_count=sum(status == "completed" for _, _, status in analyses),
        insufficient_count=sum(status == "insufficient" for _, _, status in analyses),
        analyses_with_feedback=analyses_with_feedback,
        feedback_coverage_rate=_rate(analyses_with_feedback, analysis_count),
    )
    return IncidentAnalysisOperationalReport(
        metrics_version=OPERATIONAL_METRICS_VERSION,
        generated_at=datetime.now(UTC),
        filters=filters,
        cohort=cohort,
        feedback=feedback,
        resolutions=_resolution_metrics(
            db,
            analysis_ids=analysis_ids,
            incident_ids=incident_ids,
        ),
        interpretation_warnings=list(INTERPRETATION_WARNINGS),
    )
