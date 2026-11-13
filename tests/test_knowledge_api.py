from fastapi.testclient import TestClient


def _create_document(client: TestClient) -> dict:
    response = client.post(
        "/knowledge/documents",
        json={
            "title": "Synthetic cooler manual",
            "document_type": "operation_manual",
            "description": "Test document",
            "language": "ru",
            "source_name": "FactoryMind demo warehouse",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_equipment(client: TestClient) -> dict:
    response = client.post(
        "/equipment",
        json={
            "code": "KB-API-COOLER",
            "name": "Knowledge API cooler",
            "equipment_type": "cooling_unit",
            "location": "Test shop",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_knowledge_document_upload_applicability_and_download(
    client: TestClient,
) -> None:
    equipment = _create_equipment(client)
    document = _create_document(client)
    content = b"Cooling unit maintenance instructions"

    upload = client.post(
        f"/knowledge/documents/{document['id']}/versions",
        data={
            "version": "v1",
            "source_uri": "warehouse://manuals/cooler",
        },
        files={"file": ("manual.md", content, "text/markdown")},
    )
    assert upload.status_code == 201, upload.text
    version = upload.json()
    assert version["status"] == "uploaded"
    assert version["is_current"] is True

    applicability = client.post(
        f"/knowledge/versions/{version['id']}/applicability",
        json={"equipment_type": "cooling_unit", "notes": "Demo inventory"},
    )
    assert applicability.status_code == 201, applicability.text

    filtered = client.get(
        "/knowledge/documents",
        params={"equipment_id": equipment["id"]},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [document["id"]]

    detail = client.get(f"/knowledge/documents/{document['id']}")
    assert detail.status_code == 200
    assert (
        detail.json()["versions"][0]["applicability"][0]["equipment_type"]
        == "cooling_unit"
    )
    assert "content" not in detail.json()["versions"][0]

    download = client.get(f"/knowledge/versions/{version['id']}/download")
    assert download.status_code == 200
    assert download.content == content
    assert download.headers["content-type"].startswith("text/markdown")
    assert "manual.md" in download.headers["content-disposition"]
    assert len(download.headers["x-content-sha256"]) == 64

    removed = client.delete(
        f"/knowledge/applicability/{applicability.json()['id']}",
    )
    assert removed.status_code == 204
    filtered = client.get(
        "/knowledge/documents",
        params={"equipment_id": equipment["id"]},
    )
    assert filtered.json() == []


def test_knowledge_api_rejects_invalid_and_duplicate_files(
    client: TestClient,
) -> None:
    document = _create_document(client)
    path = f"/knowledge/documents/{document['id']}/versions"

    invalid = client.post(
        path,
        data={"version": "v1"},
        files={"file": ("manual.pdf", b"not a pdf", "application/pdf")},
    )
    assert invalid.status_code == 422
    assert "сигнатуру PDF" in invalid.json()["detail"]

    first = client.post(
        path,
        data={"version": "v1"},
        files={"file": ("manual.txt", b"first", "text/plain")},
    )
    assert first.status_code == 201
    duplicate = client.post(
        path,
        data={"version": "v1"},
        files={"file": ("manual.txt", b"second", "text/plain")},
    )
    assert duplicate.status_code == 409


def test_knowledge_api_returns_not_found(client: TestClient) -> None:
    assert client.get("/knowledge/documents/999").status_code == 404
    assert client.get("/knowledge/versions/999/download").status_code == 404
    assert (
        client.get("/knowledge/documents", params={"equipment_id": 999}).status_code
        == 404
    )
    assert client.delete("/knowledge/applicability/999").status_code == 404
    upload = client.post(
        "/knowledge/documents/999/versions",
        data={"version": "v1"},
        files={"file": ("manual.txt", b"content", "text/plain")},
    )
    assert upload.status_code == 404
    response = client.post(
        "/knowledge/versions/999/applicability",
        json={"equipment_type": "cooling_unit"},
    )
    assert response.status_code == 404


def test_knowledge_api_rejects_unknown_and_duplicate_applicability(
    client: TestClient,
) -> None:
    document = _create_document(client)
    upload = client.post(
        f"/knowledge/documents/{document['id']}/versions",
        data={"version": "v1"},
        files={"file": ("manual.txt", b"content", "text/plain")},
    )
    version_id = upload.json()["id"]

    unknown_type = client.post(
        f"/knowledge/versions/{version_id}/applicability",
        json={"equipment_type": "unknown"},
    )
    assert unknown_type.status_code == 404
    unknown_equipment = client.post(
        f"/knowledge/versions/{version_id}/applicability",
        json={"equipment_id": 999},
    )
    assert unknown_equipment.status_code == 404

    equipment = _create_equipment(client)
    path = f"/knowledge/versions/{version_id}/applicability"
    assert client.post(path, json={"equipment_id": equipment["id"]}).status_code == 201
    duplicate = client.post(path, json={"equipment_id": equipment["id"]})
    assert duplicate.status_code == 409


def _upload_process_and_apply(
    client: TestClient,
    document_id: int,
    *,
    version: str,
    content: str,
    equipment_type: str,
) -> dict:
    upload = client.post(
        f"/knowledge/documents/{document_id}/versions",
        data={"version": version},
        files={"file": (f"{version}.txt", content.encode(), "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    stored = upload.json()
    applicability = client.post(
        f"/knowledge/versions/{stored['id']}/applicability",
        json={"equipment_type": equipment_type},
    )
    assert applicability.status_code == 201, applicability.text
    processed = client.post(f"/knowledge/versions/{stored['id']}/process")
    assert processed.status_code == 200, processed.text
    assert processed.json()["status"] == "ready"
    return stored


def test_process_and_search_only_current_applicable_documents(
    client: TestClient,
) -> None:
    cooler = _create_equipment(client)
    pump_response = client.post(
        "/equipment",
        json={
            "code": "KB-API-PUMP",
            "name": "Knowledge API pump",
            "equipment_type": "pump",
            "location": "Test shop",
        },
    )
    assert pump_response.status_code == 201
    pump = pump_response.json()

    cooling_document = _create_document(client)
    old_version = _upload_process_and_apply(
        client,
        cooling_document["id"],
        version="v1",
        content="Давление масла старое значение.",
        equipment_type="cooling_unit",
    )
    current_version = _upload_process_and_apply(
        client,
        cooling_document["id"],
        version="v2",
        content="Давление масла должно быть 5 бар. Проверить фильтр.",
        equipment_type="cooling_unit",
    )

    pump_document = client.post(
        "/knowledge/documents",
        json={
            "title": "Pump manual",
            "document_type": "operation_manual",
            "language": "ru",
            "source_name": "FactoryMind demo warehouse",
        },
    ).json()
    _upload_process_and_apply(
        client,
        pump_document["id"],
        version="v1",
        content="Давление масла насоса равно 7 бар.",
        equipment_type="pump",
    )

    response = client.get(
        "/knowledge/search",
        params={"q": "давление масла", "equipment_id": cooler["id"]},
    )
    assert response.status_code == 200, response.text
    results = response.json()
    assert len(results) == 1
    assert results[0]["document_version_id"] == current_version["id"]
    assert results[0]["document_version_id"] != old_version["id"]
    assert results[0]["page_start"] is None
    assert len(results[0]["checksum_sha256"]) == 64

    pump_results = client.get(
        "/knowledge/search",
        params={"q": "давление масла", "equipment_id": pump["id"]},
    )
    assert pump_results.status_code == 200
    assert [item["document_id"] for item in pump_results.json()] == [
        pump_document["id"]
    ]


def test_process_and_search_validation_errors(client: TestClient) -> None:
    assert client.post("/knowledge/versions/999/process").status_code == 404
    assert (
        client.get(
            "/knowledge/search",
            params={"q": "давление", "equipment_id": 999},
        ).status_code
        == 404
    )
    equipment = _create_equipment(client)
    assert (
        client.get(
            "/knowledge/search",
            params={"q": "x", "equipment_id": equipment["id"]},
        ).status_code
        == 422
    )
