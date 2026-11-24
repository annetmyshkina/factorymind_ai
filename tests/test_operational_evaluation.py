from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.models import LLMCall
from app.incidents.models import IncidentAnalysis


def _create_incident(client: TestClient, equipment_id: int, title: str) -> dict:
    response = client.post(
        "/incidents",
        json={
            "equipment_id": equipment_id,
            "title": title,
            "severity": "high",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _analysis(
    db: Session,
    *,
    incident_id: int,
    created_at: datetime,
    status: str = "completed",
    provider: str = "compatible",
    model: str = "model-a",
) -> IncidentAnalysis:
    call_id = None
    if status == "completed":
        call = LLMCall(
            provider=provider,
            model=model,
            prompt_version="incident-analysis-v2",
            request_messages=[{"role": "user", "content": "diagnose"}],
            parameters={"temperature": 0.0, "max_tokens": 1200},
            response_text="{}",
            status="success",
            error_type=None,
            error_message=None,
            latency_ms=20,
            created_at=created_at,
        )
        db.add(call)
        db.flush()
        call_id = call.id
    analysis = IncidentAnalysis(
        incident_id=incident_id,
        llm_call_id=call_id,
        query="давление масла",
        prompt_version="incident-analysis-v2",
        status=status,
        result={
            "observed_facts": [],
            "possible_causes": [],
            "required_checks": [],
            "recommendations": [],
            "insufficient_data": ["Тестовая запись"],
            "warnings": [],
        },
        created_at=created_at,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def _resolve(client: TestClient, incident_id: int) -> None:
    for target in ("in_progress", "resolved"):
        response = client.patch(
            f"/incidents/{incident_id}",
            json={"status": target},
        )
        assert response.status_code == 200, response.text


def _confirm(
    client: TestClient,
    *,
    incident_id: int,
    analysis_id: int,
    reason: str | None = None,
) -> None:
    payload = {
        "analysis_id": analysis_id,
        "checks_performed": ["Проверено давление масла"],
        "confirmed_cause": "Загрязнение фильтра",
        "actions_taken": ["Фильтр заменён"],
        "outcome": "Температура нормализовалась",
        "actor": "engineer",
    }
    if reason is not None:
        payload["reason"] = reason
    response = client.post(
        f"/incidents/{incident_id}/resolution",
        json=payload,
    )
    assert response.status_code == 201, response.text


def _feedback(
    client: TestClient,
    *,
    incident_id: int,
    analysis_id: int,
    rating: str,
) -> None:
    response = client.post(
        f"/incidents/{incident_id}/analyses/{analysis_id}/feedback",
        json={"rating": rating, "actor": "operator"},
    )
    assert response.status_code == 201, response.text


def _seed_operational_history(
    client: TestClient,
    db: Session,
    equipment_id: int,
) -> tuple[datetime, IncidentAnalysis, IncidentAnalysis, IncidentAnalysis]:
    now = datetime.now(UTC)
    first_incident = _create_incident(client, equipment_id, "Первый инцидент")
    second_incident = _create_incident(client, equipment_id, "Второй инцидент")
    first = _analysis(
        db,
        incident_id=first_incident["id"],
        created_at=now - timedelta(days=2),
    )
    insufficient = _analysis(
        db,
        incident_id=first_incident["id"],
        created_at=now - timedelta(days=1),
        status="insufficient",
    )
    second = _analysis(
        db,
        incident_id=second_incident["id"],
        created_at=now,
        provider="ollama",
        model="model-b",
    )

    _feedback(
        client,
        incident_id=first_incident["id"],
        analysis_id=first.id,
        rating="helpful",
    )
    _feedback(
        client,
        incident_id=first_incident["id"],
        analysis_id=first.id,
        rating="incorrect",
    )
    _feedback(
        client,
        incident_id=second_incident["id"],
        analysis_id=second.id,
        rating="unhelpful",
    )

    _resolve(client, first_incident["id"])
    _confirm(
        client,
        incident_id=first_incident["id"],
        analysis_id=first.id,
    )
    corrected = client.patch(
        f"/incidents/{first_incident['id']}/resolution",
        json={
            "confirmed_cause": "Частичное загрязнение фильтра",
            "actor": "senior-engineer",
            "reason": "Причина уточнена",
        },
    )
    assert corrected.status_code == 200, corrected.text
    revoked = client.post(
        f"/incidents/{first_incident['id']}/resolution/revoke",
        json={"actor": "quality", "reason": "Повторная проверка"},
    )
    assert revoked.status_code == 200, revoked.text
    _confirm(
        client,
        incident_id=first_incident["id"],
        analysis_id=first.id,
        reason="Результат подтверждён повторно",
    )

    _resolve(client, second_incident["id"])
    _confirm(
        client,
        incident_id=second_incident["id"],
        analysis_id=second.id,
    )
    return now, first, insufficient, second


def test_operational_metrics_keep_denominators_separate(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    _seed_operational_history(client, db_session, equipment["id"])

    response = client.get("/evaluations/operational/incident-analyses")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["metrics_version"] == "incident-operational-v1"
    assert data["filters"] == {
        "provider": None,
        "model": None,
        "prompt_version": None,
        "created_from": None,
        "created_to": None,
    }
    assert data["cohort"] == {
        "analysis_count": 3,
        "incident_count": 2,
        "completed_count": 2,
        "insufficient_count": 1,
        "analyses_with_feedback": 2,
        "feedback_coverage_rate": 2 / 3,
    }
    assert data["feedback"] == {
        "entry_count": 3,
        "helpful_count": 1,
        "unhelpful_count": 1,
        "incorrect_count": 1,
        "helpful_rate": 1 / 3,
        "unhelpful_rate": 1 / 3,
        "incorrect_rate": 1 / 3,
    }
    assert data["resolutions"] == {
        "resolution_count": 2,
        "active_resolution_count": 2,
        "currently_revoked_resolution_count": 0,
        "linked_to_selected_analysis_count": 2,
        "resolution_analysis_link_rate": 1.0,
        "analyses_with_active_resolution": 2,
        "active_resolution_analysis_rate": 2 / 3,
        "corrected_resolution_count": 1,
        "corrected_resolution_rate": 0.5,
        "ever_revoked_resolution_count": 1,
        "ever_revoked_resolution_rate": 0.5,
        "reconfirmed_resolution_count": 1,
        "reconfirmed_resolution_rate": 0.5,
        "confirmed_event_count": 3,
        "corrected_event_count": 1,
        "revoked_event_count": 1,
    }
    assert len(data["interpretation_warnings"]) == 3
    assert "actor_verified=false" in data["interpretation_warnings"][1]


def test_operational_metrics_filter_analysis_cohort(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    now, first, _, second = _seed_operational_history(
        client,
        db_session,
        equipment["id"],
    )

    provider = client.get(
        "/evaluations/operational/incident-analyses",
        params={
            "provider": "compatible",
            "model": "model-a",
            "prompt_version": "incident-analysis-v2",
        },
    )
    recent = client.get(
        "/evaluations/operational/incident-analyses",
        params={"created_from": (now - timedelta(hours=1)).isoformat()},
    )
    older = client.get(
        "/evaluations/operational/incident-analyses",
        params={"created_to": (now - timedelta(hours=1)).isoformat()},
    )

    assert provider.status_code == recent.status_code == older.status_code == 200
    provider_data = provider.json()
    assert provider_data["cohort"]["analysis_count"] == 1
    assert provider_data["cohort"]["completed_count"] == 1
    assert provider_data["feedback"]["entry_count"] == 2
    assert provider_data["resolutions"]["resolution_count"] == 1
    assert provider_data["resolutions"]["corrected_resolution_rate"] == 1
    assert provider_data["filters"]["provider"] == "compatible"
    assert first.id != second.id

    recent_data = recent.json()
    assert recent_data["cohort"]["analysis_count"] == 1
    assert recent_data["feedback"]["unhelpful_rate"] == 1
    assert recent_data["resolutions"]["resolution_count"] == 1

    older_data = older.json()
    assert older_data["cohort"]["analysis_count"] == 2
    assert older_data["cohort"]["insufficient_count"] == 1
    assert older_data["feedback"]["entry_count"] == 2
    assert older_data["resolutions"]["resolution_count"] == 1


def test_operational_metrics_empty_cohort_and_period_validation(
    client: TestClient,
) -> None:
    empty = client.get(
        "/evaluations/operational/incident-analyses",
        params={"model": "missing-model"},
    )
    invalid_period = client.get(
        "/evaluations/operational/incident-analyses",
        params={
            "created_from": "2026-11-17T12:00:00Z",
            "created_to": "2026-11-16T12:00:00Z",
        },
    )
    naive_time = client.get(
        "/evaluations/operational/incident-analyses",
        params={"created_from": "2026-11-17T12:00:00"},
    )

    assert empty.status_code == 200
    assert empty.json()["cohort"]["analysis_count"] == 0
    assert empty.json()["feedback"]["helpful_rate"] is None
    assert empty.json()["resolutions"]["corrected_resolution_rate"] is None
    assert invalid_period.status_code == 422
    assert naive_time.status_code == 422
