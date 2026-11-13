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
