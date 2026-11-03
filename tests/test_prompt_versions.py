from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import PromptVersion


def _create_prompt(
    client: TestClient,
    *,
    name: str = "incident-analysis",
    version: str = "v1",
    content: str = "Проанализируй инцидент",
) -> dict:
    response = client.post(
        "/ai/prompts",
        json={"name": name, "version": version, "content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_prompt_version(
    client: TestClient,
    db_session: Session,
) -> None:
    data = _create_prompt(client)

    assert data["id"] > 0
    assert data["name"] == "incident-analysis"
    assert data["version"] == "v1"
    assert data["content"] == "Проанализируй инцидент"
    assert data["created_at"]

    saved = db_session.scalar(select(PromptVersion))
    assert saved is not None
    assert saved.id == data["id"]


def test_duplicate_prompt_version_conflict(
    client: TestClient,
    db_session: Session,
) -> None:
    _create_prompt(client)

    response = client.post(
        "/ai/prompts",
        json={
            "name": "incident-analysis",
            "version": "v1",
            "content": "Другой текст",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Версия промпта уже существует"}
    assert len(list(db_session.scalars(select(PromptVersion)))) == 1


def test_same_name_allows_new_version(client: TestClient) -> None:
    _create_prompt(client, version="v1")
    _create_prompt(client, version="v2")

    response = client.get("/ai/prompts?name=incident-analysis")

    assert len(response.json()) == 2


def test_same_version_allows_new_name(client: TestClient) -> None:
    _create_prompt(client, name="prompt-a", version="v1")
    _create_prompt(client, name="prompt-b", version="v1")

    response = client.get("/ai/prompts")

    assert len(response.json()) == 2


def test_get_prompt_version(
    client: TestClient,
) -> None:
    created = _create_prompt(client)

    response = client.get(f"/ai/prompts/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_prompt_version_404(client: TestClient) -> None:
    response = client.get("/ai/prompts/9999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Версия промпта не найдена"}


def test_list_prompt_versions_filter_and_pagination(
    client: TestClient,
) -> None:
    _create_prompt(client, name="prompt-b", version="v1")
    _create_prompt(client, name="prompt-a", version="v2")
    _create_prompt(client, name="prompt-a", version="v1")

    response = client.get("/ai/prompts")
    assert response.status_code == 200
    assert [(item["name"], item["version"]) for item in response.json()] == [
        ("prompt-a", "v2"),
        ("prompt-a", "v1"),
        ("prompt-b", "v1"),
    ]

    response = client.get("/ai/prompts?name=prompt-a")
    assert [(item["name"], item["version"]) for item in response.json()] == [
        ("prompt-a", "v2"),
        ("prompt-a", "v1"),
    ]

    response = client.get("/ai/prompts?limit=2")
    assert len(response.json()) == 2

    response = client.get("/ai/prompts?limit=2&offset=2")
    assert [(item["name"], item["version"]) for item in response.json()] == [
        ("prompt-b", "v1"),
    ]


def test_prompt_version_is_immutable(client: TestClient) -> None:
    created = _create_prompt(client)
    url = f"/ai/prompts/{created['id']}"

    assert client.patch(url, json={"content": "Новый текст"}).status_code == 405
    assert client.delete(url).status_code == 405


def test_prompt_version_validation(client: TestClient) -> None:
    payload = {
        "name": "prompt",
        "version": "v1",
        "content": "Текст",
    }

    for overrides in (
        {"name": ""},
        {"version": ""},
        {"content": ""},
        {"name": "x" * 101},
        {"version": "v" * 51},
    ):
        response = client.post("/ai/prompts", json={**payload, **overrides})
        assert response.status_code == 422, overrides
