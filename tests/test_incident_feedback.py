from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incidents.models import (
    IncidentAnalysisFeedback,
    IncidentResolution,
    IncidentResolutionEvent,
)


def _create_incident(client: TestClient, equipment_id: int, title: str = "Incident"):
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


def _create_insufficient_analysis(client: TestClient, incident_id: int) -> dict:
    response = client.post(
        f"/incidents/{incident_id}/analyses",
        json={
            "query": "несуществующая инструкция",
            "provider": "compatible",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "insufficient"
    return response.json()


def _resolve_incident(client: TestClient, incident_id: int) -> None:
    for target in ("in_progress", "resolved"):
        response = client.patch(
            f"/incidents/{incident_id}",
            json={"status": target},
        )
        assert response.status_code == 200, response.text


def _resolution_payload(analysis_id: int | None = None) -> dict:
    return {
        "analysis_id": analysis_id,
        "checks_performed": ["Измерено давление масла", "Осмотрен фильтр"],
        "confirmed_cause": "Загрязнение масляного фильтра",
        "actions_taken": ["Фильтр заменён"],
        "outcome": "Температура вернулась в рабочий диапазон",
        "actor": "engineer@example.test",
    }


def test_feedback_is_immutable_opinion_not_confirmed_resolution(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    analysis = _create_insufficient_analysis(client, incident["id"])
    path = f"/incidents/{incident['id']}/analyses/{analysis['id']}/feedback"

    first = client.post(
        path,
        json={
            "rating": "unhelpful",
            "comment": "Недостаточно данных о давлении",
            "actor": "operator-1",
        },
    )
    second = client.post(
        path,
        json={"rating": "incorrect", "actor": "engineer-2"},
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["actor"] == "test-admin"
    assert first.json()["actor_verified"] is True
    feedback = client.get(path)
    assert feedback.status_code == 200
    assert [item["rating"] for item in feedback.json()] == [
        "unhelpful",
        "incorrect",
    ]
    assert db_session.scalar(select(IncidentResolution)) is None
    assert len(list(db_session.scalars(select(IncidentAnalysisFeedback)))) == 2


def test_confirm_correct_revoke_and_reconfirm_resolution(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    analysis = _create_insufficient_analysis(client, incident["id"])
    path = f"/incidents/{incident['id']}/resolution"
    payload = _resolution_payload(analysis["id"])

    too_early = client.post(path, json=payload)
    assert too_early.status_code == 409
    assert "resolved или closed" in too_early.json()["detail"]

    _resolve_incident(client, incident["id"])
    confirmed = client.post(path, json=payload)
    assert confirmed.status_code == 201, confirmed.text
    data = confirmed.json()
    assert data["is_active"] is True
    assert data["revision"] == 1
    assert data["analysis_id"] == analysis["id"]
    assert data["actor"] == "test-admin"
    assert data["actor_verified"] is True
    assert client.post(path, json=payload).status_code == 409

    corrected = client.patch(
        path,
        json={
            "confirmed_cause": "Частичное засорение фильтра",
            "outcome": "После замены фильтра температура нормализовалась",
            "actor": "senior-engineer",
            "reason": "Уточнена причина после разборки",
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["revision"] == 2
    assert corrected.json()["confirmed_cause"] == "Частичное засорение фильтра"

    no_changes = client.patch(
        path,
        json={
            "outcome": corrected.json()["outcome"],
            "actor": "senior-engineer",
            "reason": "Повтор",
        },
    )
    assert no_changes.status_code == 409

    revoked = client.post(
        f"{path}/revoke",
        json={
            "actor": "quality-engineer",
            "reason": "Причина требует повторной проверки",
        },
    )
    assert revoked.status_code == 200
    assert revoked.json()["is_active"] is False
    assert revoked.json()["revision"] == 3
    assert revoked.json()["revoked_at"] is not None
    assert (
        client.post(
            f"{path}/revoke",
            json={
                "actor": "quality-engineer",
                "reason": "Повтор",
            },
        ).status_code
        == 409
    )
    assert (
        client.patch(
            path,
            json={
                "outcome": "new",
                "actor": "engineer",
                "reason": "Нельзя исправлять отозванное",
            },
        ).status_code
        == 409
    )
    reconfirm_without_reason = client.post(
        path,
        json=_resolution_payload(analysis["id"]),
    )
    assert reconfirm_without_reason.status_code == 409
    assert "требует указать причину" in reconfirm_without_reason.json()["detail"]

    reconfirm_payload = _resolution_payload(analysis["id"])
    reconfirm_payload["confirmed_cause"] = "Причина подтверждена повторной проверкой"
    reconfirm_payload["reason"] = "Повторная диагностика завершена"
    reconfirmed = client.post(path, json=reconfirm_payload)
    assert reconfirmed.status_code == 201, reconfirmed.text
    assert reconfirmed.json()["is_active"] is True
    assert reconfirmed.json()["revision"] == 4

    events = client.get(f"{path}/events")
    assert events.status_code == 200
    event_data = events.json()
    assert [item["event_type"] for item in event_data] == [
        "confirmed",
        "corrected",
        "revoked",
        "confirmed",
    ]
    assert all(item["actor"] == "test-admin" for item in event_data)
    assert all(item["actor_verified"] is True for item in event_data)
    assert event_data[0]["before_snapshot"] is None
    assert event_data[1]["before_snapshot"]["revision"] == 1
    assert event_data[1]["after_snapshot"]["revision"] == 2
    assert event_data[2]["after_snapshot"]["is_active"] is False
    assert event_data[3]["before_snapshot"]["is_active"] is False

    saved_events = list(db_session.scalars(select(IncidentResolutionEvent)))
    assert len(saved_events) == 4


def test_reopening_incident_automatically_revokes_resolution(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    _resolve_incident(client, incident["id"])
    path = f"/incidents/{incident['id']}/resolution"
    assert client.post(path, json=_resolution_payload()).status_code == 201

    reopened = client.patch(
        f"/incidents/{incident['id']}",
        json={"status": "in_progress"},
    )

    assert reopened.status_code == 200, reopened.text
    resolution = client.get(path).json()
    assert resolution["is_active"] is False
    assert resolution["revision"] == 2
    events = client.get(f"{path}/events").json()
    assert [item["event_type"] for item in events] == ["confirmed", "revoked"]
    assert events[-1]["actor"] == "test-admin"
    assert events[-1]["actor_verified"] is True
    assert events[-1]["reason"] == "Инцидент возвращён в активный статус"


def test_feedback_and_resolution_reject_foreign_analysis(
    client: TestClient,
    equipment: dict,
) -> None:
    first = _create_incident(client, equipment["id"], "First")
    second = _create_incident(client, equipment["id"], "Second")
    analysis = _create_insufficient_analysis(client, first["id"])

    feedback = client.post(
        f"/incidents/{second['id']}/analyses/{analysis['id']}/feedback",
        json={"rating": "helpful", "actor": "engineer"},
    )
    assert feedback.status_code == 404

    _resolve_incident(client, second["id"])
    resolution = client.post(
        f"/incidents/{second['id']}/resolution",
        json=_resolution_payload(analysis["id"]),
    )
    assert resolution.status_code == 404


def test_resolution_endpoints_return_not_found_and_validate_payload(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    path = f"/incidents/{incident['id']}/resolution"
    assert client.get(path).status_code == 404
    assert client.get(f"{path}/events").status_code == 404
    assert (
        client.patch(
            path,
            json={"actor": "engineer", "reason": "Нет полей"},
        ).status_code
        == 422
    )
    assert client.get("/incidents/999/resolution").status_code == 404
