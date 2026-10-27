from fastapi.testclient import TestClient

TELEMETRY_DATA = {
    "temperature_c": 78.5,
    "vibration_mm_s": 4.2,
}


def test_create_telemetry_created(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json=TELEMETRY_DATA,
    )

    assert response.status_code == 201, response.text

    data = response.json()

    assert data["id"] > 0
    assert data["equipment_id"] == equipment["id"]
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
    equipment: dict,
) -> None:
    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={
            **TELEMETRY_DATA,
            "vibration_mm_s": -1.0,
        },
    )

    assert response.status_code == 422


def test_create_telemetry_rejects_nan_temperature(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={
            **TELEMETRY_DATA,
            "temperature_c": "NaN",
        },
    )

    assert response.status_code == 422


def test_create_telemetry_rejects_infinite_vibration(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={
            **TELEMETRY_DATA,
            "vibration_mm_s": "Infinity",
        },
    )

    assert response.status_code == 422


def test_get_telemetry_returns_measurements(
    client: TestClient,
    equipment: dict,
) -> None:
    equipment_id = equipment["id"]

    measurements = [
        {"temperature_c": 78.5, "vibration_mm_s": 4.2},
        {"temperature_c": 80.1, "vibration_mm_s": 4.5},
    ]

    for measurement in measurements:
        response = client.post(
            f"/equipment/{equipment_id}/telemetry",
            json=measurement,
        )
        assert response.status_code == 201, response.text

    response = client.get(f"/equipment/{equipment_id}/telemetry")

    assert response.status_code == 200, response.text

    data = response.json()

    assert len(data) == 2
    assert {item["temperature_c"] for item in data} == {78.5, 80.1}
    assert {item["vibration_mm_s"] for item in data} == {4.2, 4.5}
    assert all(item["equipment_id"] == equipment_id for item in data)


def test_get_telemetry_404_when_equipment_not_found(
    client: TestClient,
) -> None:
    response = client.get("/equipment/999/telemetry")

    assert response.status_code == 404
    assert response.json() == {"detail": "Оборудование не найдено"}


def test_since_naive_rejected(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.get(
        f"/equipment/{equipment['id']}/telemetry",
        params={"since": "2024-01-01T00:00:00"},
    )

    assert response.status_code == 422


def test_since_after_until_rejected(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.get(
        f"/equipment/{equipment['id']}/telemetry",
        params={
            "since": "2024-02-01T00:00:00Z",
            "until": "2024-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 422


def test_since_equals_until_allowed(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.get(
        f"/equipment/{equipment['id']}/telemetry",
        params={
            "since": "2024-01-01T00:00:00Z",
            "until": "2024-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 200, response.text


def test_get_telemetry_filters_by_since(
    client: TestClient,
    equipment: dict,
) -> None:
    equipment_id = equipment["id"]

    create_response = client.post(
        f"/equipment/{equipment_id}/telemetry",
        json=TELEMETRY_DATA,
    )
    assert create_response.status_code == 201, create_response.text

    response = client.get(
        f"/equipment/{equipment_id}/telemetry",
        params={"since": "2099-01-01T00:00:00Z"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_get_telemetry_pagination(
    client: TestClient,
    equipment: dict,
) -> None:
    equipment_id = equipment["id"]

    for _ in range(5):
        response = client.post(
            f"/equipment/{equipment_id}/telemetry",
            json=TELEMETRY_DATA,
        )
        assert response.status_code == 201, response.text

    page1_response = client.get(
        f"/equipment/{equipment_id}/telemetry",
        params={"limit": 2, "offset": 0},
    )
    page2_response = client.get(
        f"/equipment/{equipment_id}/telemetry",
        params={"limit": 2, "offset": 2},
    )

    assert page1_response.status_code == 200, page1_response.text
    assert page2_response.status_code == 200, page2_response.text

    page1 = page1_response.json()
    page2 = page2_response.json()

    assert len(page1) == 2
    assert len(page2) == 2
    assert {item["id"] for item in page1}.isdisjoint(
        {item["id"] for item in page2},
    )


def test_get_telemetry_rejects_invalid_limit(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.get(
        f"/equipment/{equipment['id']}/telemetry",
        params={"limit": 0},
    )

    assert response.status_code == 422
