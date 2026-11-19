"""Технические endpoints эксплуатационной наблюдаемости."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Возвращает метрики текущего API-процесса в формате Prometheus."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
