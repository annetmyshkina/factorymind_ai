from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.incidents.models import Incident
from app.monitoring.models import EquipmentDeviation
from app.telemetry.models import EquipmentTelemetry

# Валидная цепочка переходов, приводящая инцидент в нужный статус.
_CHAIN: dict[str, list[str]] = {
    "open": [],
    "in_progress": ["in_progress"],
    "resolved": ["in_progress", "resolved"],
    "closed": ["in_progress", "resolved", "closed"],
}


def _create_incident(
    client: TestClient,
    equipment_id: int,
    *,
    title: str = "Test incident",
    severity: str = "medium",
) -> dict:
    response = client.post(
        "/incidents",
        json={
            "equipment_id": equipment_id,
            "title": title,
            "severity": severity,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_deviation(db_session: Session, equipment_id: int) -> int:
    telemetry = EquipmentTelemetry(
        equipment_id=equipment_id,
        temperature_c=80.0,
        vibration_mm_s=1.0,
    )
    db_session.add(telemetry)
    db_session.flush()

    deviation = EquipmentDeviation(
        equipment_id=equipment_id,
        telemetry_id=telemetry.id,
        metric_name="temperature_c",
        observed_value=80.0,
        threshold_value=75.0,
        message="test",
    )
    db_session.add(deviation)
    db_session.commit()
    return deviation.id


def _advance_to(
    client: TestClient,
    incident_id: int,
    status: str,
) -> None:
    """Переводит инцидент в status, проверяя каждый шаг цепочки."""
    url = f"/incidents/{incident_id}"
    for step in _CHAIN[status]:
        response = client.patch(url, json={"status": step})
        assert response.status_code == 200, response.text
        # Проверяем фактическое состояние, а не только код ответа:
        # иначе тест может пройти, так и не дойдя до нужного статуса.
        assert client.get(url).json()["status"] == step


def test_create_incident(client: TestClient, equipment: dict) -> None:
    data = _create_incident(client, equipment["id"], severity="high")

    assert data["id"] > 0
    assert data["equipment_id"] == equipment["id"]
    assert data["equipment_code"] == equipment["code"]
    assert data["status"] == "open"
    assert data["severity"] == "high"
    assert data["assigned_to"] is None
    assert data["resolved_at"] is None
    assert data["created_at"]
    assert data["updated_at"]


def test_create_incident_404_when_equipment_not_found(
    client: TestClient,
) -> None:
    response = client.post(
        "/incidents",
        json={"equipment_id": 9999, "title": "X", "severity": "low"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Оборудование не найдено"}


def test_create_incident_rejects_invalid_severity(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.post(
        "/incidents",
        json={
            "equipment_id": equipment["id"],
            "title": "X",
            "severity": "extreme",
        },
    )
    assert response.status_code == 422


def test_create_incident_rejects_empty_title(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.post(
        "/incidents",
        json={"equipment_id": equipment["id"], "title": ""},
    )
    assert response.status_code == 422


def test_list_incidents_filter_by_status(
    client: TestClient,
    equipment: dict,
) -> None:
    inc1 = _create_incident(client, equipment["id"], title="A")
    _create_incident(client, equipment["id"], title="B")
    response = client.patch(
        f"/incidents/{inc1['id']}",
        json={"status": "in_progress"},
    )
    assert response.status_code == 200, response.text

    response = client.get("/incidents?status=open")
    assert response.status_code == 200
    assert all(i["status"] == "open" for i in response.json())
    assert len(response.json()) == 1

    response = client.get("/incidents?status=in_progress")
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == inc1["id"]


def test_list_incidents_filter_by_equipment(
    client: TestClient,
    equipment: dict,
) -> None:
    # второе оборудование
    other = client.post(
        "/equipment",
        json={
            "code": "OTHER-1",
            "name": "Other",
            "equipment_type": "cooling_unit",
            "location": "X",
        },
    ).json()

    _create_incident(client, equipment["id"], title="A")
    _create_incident(client, other["id"], title="B")

    response = client.get(f"/incidents?equipment_id={equipment['id']}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["equipment_id"] == equipment["id"]


def test_list_incidents_sorted_by_created_at_desc(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    ids = [
        _create_incident(client, equipment["id"], title=f"#{i}")["id"] for i in range(3)
    ]

    # Явные метки времени, чтобы порядок не зависел от скорости создания.
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for offset, incident_id in enumerate(ids):
        incident = db_session.get(Incident, incident_id)
        assert incident is not None
        incident.created_at = base + timedelta(minutes=offset)
    db_session.commit()

    data = client.get("/incidents").json()
    assert [item["id"] for item in data] == list(reversed(ids))


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("open", "in_progress"),
        ("in_progress", "resolved"),
        ("resolved", "closed"),
        ("open", "closed"),
        ("closed", "open"),
        ("resolved", "in_progress"),
    ],
)
def test_valid_transitions(
    client: TestClient,
    equipment: dict,
    from_status: str,
    to_status: str,
) -> None:
    incident = _create_incident(client, equipment["id"])
    _advance_to(client, incident["id"], from_status)

    response = client.patch(
        f"/incidents/{incident['id']}",
        json={"status": to_status},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == to_status
    assert client.get(f"/incidents/{incident['id']}").json()["status"] == (to_status)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("open", "resolved"),
        ("resolved", "open"),
        ("closed", "in_progress"),
        ("closed", "resolved"),
    ],
)
def test_invalid_transitions(
    client: TestClient,
    equipment: dict,
    from_status: str,
    to_status: str,
) -> None:
    incident = _create_incident(client, equipment["id"])
    _advance_to(client, incident["id"], from_status)
    url = f"/incidents/{incident['id']}"

    response = client.patch(url, json={"status": to_status})
    assert response.status_code == 409
    # Отказ не должен частично менять состояние.
    assert client.get(url).json()["status"] == from_status


def test_same_status_is_noop(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    url = f"/incidents/{incident['id']}"
    events_before = client.get(f"{url}/events").json()

    response = client.patch(url, json={"status": "open"})

    assert response.status_code == 200
    assert response.json()["status"] == "open"
    assert client.get(f"{url}/events").json() == events_before


def test_resolved_at_set_and_reset(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    url = f"/incidents/{incident['id']}"

    assert client.patch(url, json={"status": "in_progress"}).status_code == 200
    assert client.patch(url, json={"status": "resolved"}).status_code == 200
    data = client.get(url).json()
    assert data["resolved_at"] is not None

    assert client.patch(url, json={"status": "in_progress"}).status_code == 200
    data = client.get(url).json()
    assert data["resolved_at"] is None


def test_events_logged(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"], severity="high")
    url = f"/incidents/{incident['id']}"

    client.patch(url, json={"status": "in_progress"})
    client.patch(url, json={"status": "resolved"})

    events = client.get(f"{url}/events").json()
    assert [e["event_type"] for e in events] == [
        "created",
        "status_changed",
        "status_changed",
    ]
    assert events[0]["payload"] == {
        "severity": "high",
        "title": "Test incident",
    }
    assert events[1]["payload"] == {
        "from": "open",
        "to": "in_progress",
        "actor": "system",
    }
    assert events[2]["payload"] == {
        "from": "in_progress",
        "to": "resolved",
        "actor": "system",
    }


def test_update_severity(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"], severity="low")
    url = f"/incidents/{incident['id']}"

    response = client.patch(url, json={"severity": "critical"})

    assert response.status_code == 200
    assert response.json()["severity"] == "critical"
    assert client.get(url).json()["severity"] == "critical"


def test_update_description(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    url = f"/incidents/{incident['id']}"

    response = client.patch(url, json={"description": "Подробности"})

    assert response.status_code == 200
    assert response.json()["description"] == "Подробности"
    assert client.get(url).json()["description"] == "Подробности"


def test_description_can_be_cleared(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    url = f"/incidents/{incident['id']}"
    client.patch(url, json={"description": "Подробности"})

    response = client.patch(url, json={"description": None})

    assert response.status_code == 200
    assert response.json()["description"] is None


def test_assign_and_unassign_logs_events(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    url = f"/incidents/{incident['id']}"

    response = client.patch(url, json={"assigned_to": "ivan"})
    assert response.status_code == 200
    assert response.json()["assigned_to"] == "ivan"

    response = client.patch(url, json={"assigned_to": None})
    assert response.status_code == 200
    assert response.json()["assigned_to"] is None

    events = client.get(f"{url}/events").json()
    assigned = [e for e in events if e["event_type"] == "assigned"]
    assert [e["payload"] for e in assigned] == [
        {"from": None, "to": "ivan", "actor": "system"},
        {"from": "ivan", "to": None, "actor": "system"},
    ]


def test_update_rejects_invalid_status(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])

    response = client.patch(
        f"/incidents/{incident['id']}",
        json={"status": "bogus"},
    )
    assert response.status_code == 422


def test_get_incident_404(client: TestClient) -> None:
    response = client.get("/incidents/9999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Инцидент не найден"}


def test_update_incident_404(client: TestClient) -> None:
    response = client.patch("/incidents/9999", json={"status": "in_progress"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Инцидент не найден"}


def test_list_events_404(client: TestClient) -> None:
    response = client.get("/incidents/9999/events")
    assert response.status_code == 404
    assert response.json() == {"detail": "Инцидент не найден"}


def test_link_deviation_and_idempotency(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    deviation_id = _create_deviation(db_session, equipment["id"])
    incident = _create_incident(client, equipment["id"])
    url = f"/incidents/{incident['id']}/deviations"

    # первая привязка — 204
    response = client.post(url, json={"deviation_id": deviation_id})
    assert response.status_code == 204

    # повторная — идемпотентно — 204
    response = client.post(url, json={"deviation_id": deviation_id})
    assert response.status_code == 204

    # детали содержат deviation_ids
    data = client.get(f"/incidents/{incident['id']}").json()
    assert data["deviation_ids"] == [deviation_id]

    # повторная привязка не должна дублировать событие аудита
    events = client.get(f"/incidents/{incident['id']}/events").json()
    linked = [e for e in events if e["event_type"] == "deviation_linked"]
    assert len(linked) == 1
    assert linked[0]["payload"] == {"deviation_id": deviation_id}


def test_link_deviation_conflict_when_linked_to_other(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    deviation_id = _create_deviation(db_session, equipment["id"])

    inc1 = _create_incident(client, equipment["id"], title="A")
    inc2 = _create_incident(client, equipment["id"], title="B")

    client.post(
        f"/incidents/{inc1['id']}/deviations",
        json={"deviation_id": deviation_id},
    )
    response = client.post(
        f"/incidents/{inc2['id']}/deviations",
        json={"deviation_id": deviation_id},
    )
    assert response.status_code == 409


def test_link_missing_deviation_404(
    client: TestClient,
    equipment: dict,
) -> None:
    incident = _create_incident(client, equipment["id"])
    url = f"/incidents/{incident['id']}"

    response = client.post(
        f"{url}/deviations",
        json={"deviation_id": 9999},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Отклонение не найдено"}
    assert client.get(url).json()["deviation_ids"] == []
    events = client.get(f"{url}/events").json()
    assert [e["event_type"] for e in events] == ["created"]


def test_list_incidents_no_n_plus_1(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    for _ in range(3):
        _create_incident(client, equipment["id"])

    queries: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", _capture)
    try:
        response = client.get("/incidents")
    finally:
        event.remove(db_session.bind, "before_cursor_execute", _capture)

    assert response.status_code == 200
    assert len(response.json()) == 3
    assert len(queries) == 1, f"Possible N+1: {len(queries)} queries"


def test_get_incident_no_n_plus_1(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    incident = _create_incident(client, equipment["id"])
    url = f"/incidents/{incident['id']}"

    for _ in range(2):
        client.post(
            f"{url}/deviations",
            json={"deviation_id": _create_deviation(db_session, equipment["id"])},
        )
    for step in ("in_progress", "resolved", "closed"):
        assert client.patch(url, json={"status": step}).status_code == 200

    queries: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", _capture)
    try:
        response = client.get(url)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", _capture)

    assert response.status_code == 200
    assert len(response.json()["deviation_ids"]) == 2
    assert len(response.json()["events"]) == 6
    # 3 запроса сейчас (incident+equipment, deviations, events);
    # при N+1 их было бы больше с ростом числа связанных строк.
    assert len(queries) <= 4, f"Possible N+1: {len(queries)} queries"
