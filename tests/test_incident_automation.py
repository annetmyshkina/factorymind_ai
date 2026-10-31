import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incidents.models import Incident, IncidentDeviation
from app.monitoring.models import EquipmentDeviation, MonitoringRule
from app.telemetry.models import EquipmentTelemetry
from app.telemetry.mqtt.handler import handle_message


def _create_rule(
    db_session: Session,
    equipment_id: int,
    *,
    metric_name: str = "temperature_c",
    operator: str = "gt",
    threshold_value: float = 80.0,
) -> MonitoringRule:
    rule = MonitoringRule(
        equipment_id=equipment_id,
        name=f"Rule {metric_name}",
        metric_name=metric_name,
        operator=operator,
        threshold_value=threshold_value,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    return rule


def _post_telemetry(
    client: TestClient,
    equipment_id: int,
    payload: dict[str, Any],
) -> dict:
    response = client.post(
        f"/equipment/{equipment_id}/telemetry",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _incidents(db_session: Session) -> list[Incident]:
    return list(db_session.scalars(select(Incident).order_by(Incident.id)))


def test_deviation_creates_incident(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0)

    _post_telemetry(
        client,
        equipment["id"],
        {"temperature_c": 85.0, "vibration_mm_s": 1.0},
    )

    incidents = _incidents(db_session)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.status == "open"
    assert incident.severity == "critical"
    assert "Температура" in incident.title
    assert incident.description

    deviation = db_session.scalar(select(EquipmentDeviation))
    assert deviation is not None

    detail = client.get(f"/incidents/{incident.id}").json()
    assert detail["deviation_ids"] == [deviation.id]
    assert [e["event_type"] for e in detail["events"]] == [
        "created",
        "deviation_linked",
    ]
    assert detail["events"][1]["payload"] == {"deviation_id": deviation.id}


@pytest.mark.parametrize(
    ("metric_name", "threshold", "payload", "expected_severity"),
    [
        (
            "temperature_c",
            80.0,
            {"temperature_c": 85.0, "vibration_mm_s": 1.0},
            "critical",
        ),
        (
            "vibration_mm_s",
            5.0,
            {"temperature_c": 70.0, "vibration_mm_s": 9.0},
            "high",
        ),
        (
            "ambient_temperature_c",
            30.0,
            {
                "temperature_c": 70.0,
                "vibration_mm_s": 1.0,
                "ambient_temperature_c": 35.0,
            },
            "medium",
        ),
    ],
)
def test_severity_depends_on_metric(
    client: TestClient,
    equipment: dict,
    db_session: Session,
    metric_name: str,
    threshold: float,
    payload: dict[str, Any],
    expected_severity: str,
) -> None:
    _create_rule(
        db_session,
        equipment["id"],
        metric_name=metric_name,
        threshold_value=threshold,
    )

    _post_telemetry(client, equipment["id"], payload)

    incident = _incidents(db_session)[0]
    assert incident.severity == expected_severity


def test_repeated_deviation_reuses_active_incident(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0)

    _post_telemetry(
        client,
        equipment["id"],
        {"temperature_c": 85.0, "vibration_mm_s": 1.0},
    )
    _post_telemetry(
        client,
        equipment["id"],
        {"temperature_c": 90.0, "vibration_mm_s": 1.0},
    )

    incidents = _incidents(db_session)
    assert len(incidents) == 1

    detail = client.get(f"/incidents/{incidents[0].id}").json()
    assert len(detail["deviation_ids"]) == 2
    event_types = [e["event_type"] for e in detail["events"]]
    assert event_types.count("created") == 1
    assert event_types.count("deviation_linked") == 2


def test_multiple_deviations_in_one_telemetry_share_incident(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    _create_rule(
        db_session,
        equipment["id"],
        metric_name="temperature_c",
        threshold_value=80.0,
    )
    _create_rule(
        db_session,
        equipment["id"],
        metric_name="vibration_mm_s",
        threshold_value=5.0,
    )

    _post_telemetry(
        client,
        equipment["id"],
        {"temperature_c": 85.0, "vibration_mm_s": 9.0},
    )

    incidents = _incidents(db_session)
    assert len(incidents) == 1

    detail = client.get(f"/incidents/{incidents[0].id}").json()
    assert len(detail["deviation_ids"]) == 2


@pytest.mark.parametrize(
    ("final_status", "chain"),
    [
        ("closed", ["closed"]),
        ("resolved", ["in_progress", "resolved"]),
    ],
)
def test_inactive_incident_does_not_block_new_one(
    client: TestClient,
    equipment: dict,
    db_session: Session,
    final_status: str,
    chain: list[str],
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0)

    _post_telemetry(
        client,
        equipment["id"],
        {"temperature_c": 85.0, "vibration_mm_s": 1.0},
    )
    first = _incidents(db_session)[0]

    for status in chain:
        response = client.patch(
            f"/incidents/{first.id}",
            json={"status": status},
        )
        assert response.status_code == 200, response.text

    _post_telemetry(
        client,
        equipment["id"],
        {"temperature_c": 90.0, "vibration_mm_s": 1.0},
    )

    incidents = _incidents(db_session)
    assert len(incidents) == 2
    assert incidents[0].status == final_status
    assert incidents[1].status == "open"

    detail = client.get(f"/incidents/{incidents[1].id}").json()
    assert len(detail["deviation_ids"]) == 1


def test_no_deviation_no_incident(
    client: TestClient,
    equipment: dict,
    db_session: Session,
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0)

    _post_telemetry(
        client,
        equipment["id"],
        {"temperature_c": 70.0, "vibration_mm_s": 1.0},
    )

    assert _incidents(db_session) == []
    assert db_session.scalar(select(EquipmentDeviation)) is None


def test_incident_failure_rolls_back_telemetry(
    client: TestClient,
    equipment: dict,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0)

    def _raise(*args, **kwargs):
        raise RuntimeError("incident creation failed")

    monkeypatch.setattr(
        "app.telemetry.router.ensure_incident_for_deviation",
        _raise,
    )

    with pytest.raises(RuntimeError):
        client.post(
            f"/equipment/{equipment['id']}/telemetry",
            json={"temperature_c": 85.0, "vibration_mm_s": 1.0},
        )

    assert db_session.query(EquipmentTelemetry).count() == 0
    assert db_session.query(EquipmentDeviation).count() == 0
    assert _incidents(db_session) == []


def _mqtt_payload(**overrides: Any) -> bytes:
    payload = {
        "event_id": "event-1",
        "equipment_code": "COOLER-FIXTURE",
        "measured_at": "2026-10-31T09:00:00Z",
        "temperature_c": 90.0,
        "vibration_mm_s": 1.0,
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def test_mqtt_deviation_creates_incident(
    equipment: dict,
    db_session: Session,
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0)

    handle_message(db_session, _mqtt_payload())

    incidents = _incidents(db_session)
    assert len(incidents) == 1
    assert incidents[0].severity == "critical"

    deviation = db_session.scalar(select(EquipmentDeviation))
    assert deviation is not None
    assert deviation.equipment_id == equipment["id"]

    incident = incidents[0]
    links = db_session.scalars(select(IncidentDeviation)).all()
    assert [(link.incident_id, link.deviation_id) for link in links] == [
        (incident.id, deviation.id),
    ]


def test_mqtt_duplicate_event_is_ignored(
    equipment: dict,
    db_session: Session,
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0)

    handle_message(db_session, _mqtt_payload())
    handle_message(db_session, _mqtt_payload())

    assert len(_incidents(db_session)) == 1
    assert len(list(db_session.scalars(select(EquipmentDeviation)))) == 1
