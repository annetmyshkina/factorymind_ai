import json
from pathlib import Path

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0


def test_metrics_endpoint_exports_normalized_http_route(
    client: TestClient,
) -> None:
    labels = {
        "method": "GET",
        "route": "/incidents/{incident_id}",
        "status_code": "404",
    }
    before = _sample("factorymind_http_requests_total", labels)

    response = client.get("/incidents/999")
    assert response.status_code == 404

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert "factorymind_http_requests_total" in metrics.text
    assert _sample("factorymind_http_requests_total", labels) == before + 1
    assert 'route="/incidents/999"' not in metrics.text
    assert 'route="/metrics"' not in metrics.text


def test_manual_incident_is_counted_only_after_creation(
    client: TestClient,
    equipment: dict,
) -> None:
    labels = {"source": "manual", "severity": "high"}
    before = _sample("factorymind_incidents_created_total", labels)

    response = client.post(
        "/incidents",
        json={
            "equipment_id": equipment["id"],
            "title": "Проверка observability",
            "severity": "high",
        },
    )

    assert response.status_code == 201, response.text
    assert _sample("factorymind_incidents_created_total", labels) == before + 1


def test_automatic_incident_is_counted_after_telemetry_commit(
    client: TestClient,
    equipment: dict,
) -> None:
    rule = client.post(
        f"/equipment/{equipment['id']}/monitoring-rules",
        json={
            "name": "Перегрев",
            "metric_name": "temperature_c",
            "operator": "gt",
            "threshold_value": 80,
        },
    )
    assert rule.status_code == 201, rule.text
    labels = {"source": "automatic", "severity": "critical"}
    before = _sample("factorymind_incidents_created_total", labels)

    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={"temperature_c": 85, "vibration_mm_s": 1},
    )

    assert response.status_code == 201, response.text
    assert _sample("factorymind_incidents_created_total", labels) == before + 1


def test_grafana_dashboard_is_valid_and_covers_core_flows() -> None:
    dashboard_path = Path(
        "deploy/grafana/dashboards/factorymind-overview.json",
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))

    assert dashboard["uid"] == "factorymind-overview"
    panel_titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "HTTP-запросы",
        "Обработка MQTT",
        "Созданные инциденты",
        "LLM-вызовы и latency",
        "Очередь экспериментов",
        "Очередь уведомлений",
        "Доставка Telegram",
    } <= panel_titles

    expressions = {
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    }
    assert any("factorymind_http_requests_total" in expr for expr in expressions)
    assert any("factorymind_mqtt_messages_total" in expr for expr in expressions)
    assert any("factorymind_llm_calls_total" in expr for expr in expressions)
    assert any("factorymind_experiment_queue_runs" in expr for expr in expressions)
    assert any("factorymind_notification_queue_items" in expr for expr in expressions)
