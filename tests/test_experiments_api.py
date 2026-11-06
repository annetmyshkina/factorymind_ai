import pytest
from fastapi.testclient import TestClient


def _create_prompt(client: TestClient) -> int:
    response = client.post(
        "/ai/prompts",
        json={
            "name": "experiment-api",
            "version": "v1",
            "content": "Analyse only supplied facts.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _payload(prompt_version_id: int) -> dict:
    return {
        "name": "API comparison",
        "prompt_version_id": prompt_version_id,
        "scenario": {"temperature_c": 90.0},
        "criteria": {
            "temperature": {
                "evaluator": "contains_all",
                "terms": ["temperature"],
            },
        },
        "runs": [
            {"provider": "ollama", "model": "llama3.1"},
            {"provider": "compatible", "model": "remote-model"},
        ],
    }


def test_experiment_api_create_get_and_report(
    client: TestClient,
) -> None:
    prompt_id = _create_prompt(client)

    response = client.post("/experiments", json=_payload(prompt_id))

    assert response.status_code == 201, response.text
    created = response.json()
    assert [run["status"] for run in created["runs"]] == ["pending", "pending"]

    detail = client.get(f"/experiments/{created['id']}")
    assert detail.status_code == 200
    assert detail.json() == created

    report = client.get(f"/experiments/{created['id']}/report")
    assert report.status_code == 200
    assert report.json()["run_counts"] == {
        "pending": 2,
        "running": 0,
        "completed": 0,
        "failed": 0,
    }


def test_experiment_api_rejects_missing_prompt(client: TestClient) -> None:
    response = client.post("/experiments", json=_payload(999))

    assert response.status_code == 404
    assert response.json() == {"detail": "Версия промпта не найдена"}


@pytest.mark.parametrize(
    "path",
    ["/experiments/999", "/experiments/999/report"],
)
def test_experiment_api_returns_404(path: str, client: TestClient) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Эксперимент не найден"}


def test_experiment_api_rejects_duplicate_runs(client: TestClient) -> None:
    prompt_id = _create_prompt(client)
    payload = _payload(prompt_id)
    payload["runs"] = [payload["runs"][0], payload["runs"][0]]

    response = client.post("/experiments", json=payload)

    assert response.status_code == 422
