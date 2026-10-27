from fastapi.testclient import TestClient

EQUIPMENT_DATA = {
    "code": "COOLER-001",
    "name": "Холодильный агрегат № 1",
    "equipment_type": "cooling_unit",
    "location": "Цех № 1",
}


def test_create_equipment_created(client: TestClient) -> None:
    response = client.post(
        "/equipment",
        json=EQUIPMENT_DATA,
    )

    assert response.status_code == 201, response.text

    data = response.json()

    assert data["id"] > 0
    assert data["code"] == "COOLER-001"
    assert data["name"] == "Холодильный агрегат № 1"
    assert data["equipment_type"] == "cooling_unit"
    assert data["location"] == "Цех № 1"
    assert data["is_active"] is True


def test_list_equipment_all_records(client: TestClient) -> None:
    first_response = client.post(
        "/equipment",
        json=EQUIPMENT_DATA,
    )
    assert first_response.status_code == 201, first_response.text

    second_response = client.post(
        "/equipment",
        json={
            "code": "MOTOR-001",
            "name": "Электродвигатель № 1",
            "equipment_type": "electric_motor",
            "location": "Цех № 2",
        },
    )
    assert second_response.status_code == 201, second_response.text

    response = client.get("/equipment")

    assert response.status_code == 200, response.text

    data = response.json()

    assert len(data) == 2
    assert data[0]["code"] == "COOLER-001"
    assert data[1]["code"] == "MOTOR-001"


def test_get_equipment_record(
    client: TestClient,
    equipment: dict,
) -> None:
    equipment_id = equipment["id"]

    response = client.get(f"/equipment/{equipment_id}")

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["id"] == equipment_id
    assert data["code"] == equipment["code"]
    assert data["name"] == equipment["name"]
    assert data["equipment_type"] == equipment["equipment_type"]
    assert data["location"] == equipment["location"]
    assert data["is_active"] is True


def test_get_equipment_404_when_not_found(
    client: TestClient,
) -> None:
    response = client.get("/equipment/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Оборудование не найдено"}


def test_update_equipment_updated_record(
    client: TestClient,
    equipment: dict,
) -> None:
    equipment_id = equipment["id"]

    response = client.patch(
        f"/equipment/{equipment_id}",
        json={"location": "Цех №3"},
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["id"] == equipment_id
    assert data["location"] == "Цех №3"
    assert data["code"] == equipment["code"]
    assert data["name"] == equipment["name"]
    assert data["equipment_type"] == equipment["equipment_type"]
    assert data["is_active"] is True


def test_update_equipment_404_when_not_found(
    client: TestClient,
) -> None:
    response = client.patch(
        "/equipment/999",
        json={"location": "Цех № 3"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Оборудование не найдено"}


def test_update_equipment_422_when_data_is_invalid(
    client: TestClient,
    equipment: dict,
) -> None:
    equipment_id = equipment["id"]

    empty_response = client.patch(
        f"/equipment/{equipment_id}",
        json={},
    )
    assert empty_response.status_code == 422

    null_response = client.patch(
        f"/equipment/{equipment_id}",
        json={"location": None},
    )
    assert null_response.status_code == 422


def test_create_equipment_409_when_code_exists(
    client: TestClient,
    equipment: dict,
) -> None:
    response = client.post(
        "/equipment",
        json={
            **EQUIPMENT_DATA,
            "code": equipment["code"],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Оборудование с таким кодом уже существует",
    }
