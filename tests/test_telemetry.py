from fastapi.testclient import TestClient

TELEMETRY_DATA = {
    "temperature_c": 78.5,
    "vibration_mm_s": 4.2,
}


def test_create_telemetry_created(client: TestClient) -> None:
    response = client.post(
        "/equipment",
        json={
            "code": "COOLER-001",
            "name": "Холодильный агрегат № 1",
            "equipment_type": "cooling_unit",
            "location": "Цех № 1",
        },
    )

    equipment_id = response.json()["id"]
    sender = client.post(
        f"/equipment/{equipment_id}/telemetry",
        json=TELEMETRY_DATA,
    )

    assert sender.status_code == 201

    data = sender.json()

    assert data["id"] > 0
    assert data["equipment_id"] == equipment_id
    assert data["measured_at"]
    assert data["temperature_c"] == 78.5
    assert data["vibration_mm_s"] == 4.2


def test_create_telemetry_404_when_equipment_not_found(
    client: TestClient,
) -> None:
    response = client.post(
        "/equipment/999/telemetry",
        json=TELEMETRY_DATA,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Оборудование не найдено"}


def test_create_telemetry_rejects_negative_vibration(
    client: TestClient,
) -> None:
    response = client.post(
        "/equipment/1/telemetry",
        json={
            "temperature_c": 78.5,
            "vibration_mm_s": -1.0,
        },
    )

    assert response.status_code == 422


def test_create_telemetry_rejects_nan_temperature(
    client: TestClient,
) -> None:
    response = client.post(
        "/equipment/1/telemetry",
        json={
            "temperature_c": "NaN",
            "vibration_mm_s": 4.2,
        },
    )

    assert response.status_code == 422


def test_create_telemetry_rejects_infinite_vibration(
    client: TestClient,
) -> None:
    response = client.post(
        "/equipment/1/telemetry",
        json={
            "temperature_c": 78.5,
            "vibration_mm_s": "Infinity",
        },
    )

    assert response.status_code == 422
