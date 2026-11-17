"""API read-only отчётов Evaluation Engine."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.evaluation.operational import (
    IncidentAnalysisOperationalReport,
    OperationalMetricFilters,
    build_incident_analysis_operational_report,
)

router = APIRouter(prefix="/evaluations", tags=["Evaluation"])

OperationalMetricQuery = Annotated[OperationalMetricFilters, Depends()]


@router.get(
    "/operational/incident-analyses",
    response_model=IncidentAnalysisOperationalReport,
)
def get_incident_analysis_operational_metrics(
    filters: OperationalMetricQuery,
    db: Session = Depends(get_db),
) -> IncidentAnalysisOperationalReport:
    """Возвращает субъективные и эксплуатационные сигналы выбранной когорты."""
    if (
        filters.created_from is not None
        and filters.created_to is not None
        and filters.created_from > filters.created_to
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Дата начала периода не может быть позже даты окончания",
        )
    return build_incident_analysis_operational_report(db, filters)
