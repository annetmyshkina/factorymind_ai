from fastapi.testclient import TestClient


def _create_equipment(
    client: TestClient,
    *,
    code: str,
    equipment_type: str,
) -> dict:
    response = client.post(
        "/equipment",
        json={
            "code": code,
            "name": code,
            "equipment_type": equipment_type,
            "location": "Тестовый цех",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


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


def _confirm_resolution(
    client: TestClient,
    incident_id: int,
    *,
    cause: str = "Загрязнение масляного фильтра",
) -> dict:
    for target in ("in_progress", "resolved"):
        response = client.patch(
            f"/incidents/{incident_id}",
            json={"status": target},
        )
        assert response.status_code == 200, response.text
    response = client.post(
        f"/incidents/{incident_id}/resolution",
        json={
            "checks_performed": ["Проверено давление масла"],
            "confirmed_cause": cause,
            "actions_taken": ["Масляный фильтр заменён"],
            "outcome": "Температура компрессора нормализовалась",
            "actor": "engineer@example.test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_similar_incidents_use_only_active_experience_of_same_equipment_type(
    client: TestClient,
    equipment: dict,
) -> None:
    target = _create_incident(client, equipment["id"], "Текущий перегрев")
    same_equipment = _create_incident(
        client,
        equipment["id"],
        "Предыдущий перегрев",
    )
    exact_resolution = _confirm_resolution(client, same_equipment["id"])

    same_type_equipment = _create_equipment(
        client,
        code="COOLER-SAME-TYPE",
        equipment_type=equipment["equipment_type"],
    )
    same_type_incident = _create_incident(
        client,
        same_type_equipment["id"],
        "Перегрев соседнего агрегата",
    )
    type_resolution = _confirm_resolution(client, same_type_incident["id"])

    other_equipment = _create_equipment(
        client,
        code="PUMP-OTHER-TYPE",
        equipment_type="pump",
    )
    other_incident = _create_incident(
        client,
        other_equipment["id"],
        "Нерелевантный насос",
    )
    _confirm_resolution(client, other_incident["id"])

    revoked_incident = _create_incident(
        client,
        equipment["id"],
        "Отозванный опыт",
    )
    _confirm_resolution(client, revoked_incident["id"])
    revoked = client.post(
        f"/incidents/{revoked_incident['id']}/resolution/revoke",
        json={"actor": "quality", "reason": "Причина не подтвердилась"},
    )
    assert revoked.status_code == 200, revoked.text

    response = client.get(
        f"/incidents/{target['id']}/similar-resolutions",
        params={"q": "масляного фильтра"},
    )

    assert response.status_code == 200, response.text
    results = response.json()
    assert [item["resolution_id"] for item in results] == [
        exact_resolution["id"],
        type_resolution["id"],
    ]
    assert [item["match_scope"] for item in results] == [
        "same_equipment",
        "same_equipment_type",
    ]
    assert results[0]["score"] > results[1]["score"]
    assert results[0]["citation"] == f"EXP:R{exact_resolution['id']}:V1"


def test_corrected_resolution_replaces_searchable_content(
    client: TestClient,
    equipment: dict,
) -> None:
    target = _create_incident(client, equipment["id"], "Текущий инцидент")
    historical = _create_incident(client, equipment["id"], "Исторический инцидент")
    resolution = _confirm_resolution(client, historical["id"])

    corrected = client.patch(
        f"/incidents/{historical['id']}/resolution",
        json={
            "confirmed_cause": "Ослабление приводного ремня",
            "checks_performed": ["Проверено натяжение ремня"],
            "actions_taken": ["Ремень натянут"],
            "outcome": "Вибрация устранена",
            "actor": "senior-engineer",
            "reason": "Причина уточнена после разборки",
        },
    )
    assert corrected.status_code == 200, corrected.text

    old_query = client.get(
        f"/incidents/{target['id']}/similar-resolutions",
        params={"q": "масляного фильтра"},
    )
    new_query = client.get(
        f"/incidents/{target['id']}/similar-resolutions",
        params={"q": "приводного ремня"},
    )

    assert old_query.status_code == new_query.status_code == 200
    assert old_query.json() == []
    assert new_query.json()[0]["resolution_id"] == resolution["id"]
    assert new_query.json()[0]["resolution_revision"] == 2


def test_similar_incident_search_validates_source_incident(
    client: TestClient,
) -> None:
    response = client.get(
        "/incidents/999/similar-resolutions",
        params={"q": "масляный фильтр"},
    )
    assert response.status_code == 404
