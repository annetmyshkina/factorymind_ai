import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.contracts import ChatMessage, LLMResponse, LLMUsage
from app.ai.errors import LLMTimeoutError
from app.ai.models import LLMCall
from app.ai.providers.base import LLMProvider
from app.incidents.analysis import HUMAN_REVIEW_WARNING
from app.incidents.models import IncidentAnalysis, IncidentAnalysisSource
from app.knowledge.processing import process_document_version
from app.knowledge.schemas import (
    KnowledgeApplicabilityCreate,
    KnowledgeDocumentCreate,
)
from app.knowledge.service import (
    add_applicability,
    add_document_version,
    create_document,
)
from app.monitoring.models import EquipmentDeviation
from app.telemetry.models import EquipmentTelemetry


class FakeProvider(LLMProvider):
    name = "compatible"
    model = "fake-model"

    def __init__(
        self,
        *,
        content: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.content = content
        self.error = error
        self.calls: list[list[ChatMessage]] = []
        self.closed = False

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        assert self.content is not None
        return LLMResponse(
            provider=self.name,
            model=self.model,
            content=self.content,
            latency_ms=12,
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50),
        )

    def close(self) -> None:
        self.closed = True


def _create_incident(client: TestClient, equipment_id: int) -> dict:
    response = client.post(
        "/incidents",
        json={
            "equipment_id": equipment_id,
            "title": "Повышенная температура компрессора",
            "description": "Температура растёт под нагрузкой",
            "severity": "critical",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_source(db: Session, equipment: dict) -> int:
    document = create_document(
        db,
        KnowledgeDocumentCreate(
            title="Инструкция холодильной установки",
            document_type="maintenance_instruction",
            source_name="Тестовый склад документации",
        ),
    )
    version = add_document_version(
        db,
        document.id,
        version="v1",
        filename="manual.txt",
        mime_type="text/plain",
        content=(
            "При высокой температуре проверить давление масла и состояние фильтра."
        ).encode(),
        source_uri="warehouse://manuals/cooler",
    )
    add_applicability(
        db,
        version.id,
        KnowledgeApplicabilityCreate(equipment_id=equipment["id"]),
    )
    _, chunks = process_document_version(db, version.id)
    return chunks[0].id


def _link_deviation(
    client: TestClient,
    db: Session,
    *,
    incident_id: int,
    equipment_id: int,
) -> int:
    telemetry = EquipmentTelemetry(
        equipment_id=equipment_id,
        temperature_c=82.0,
        vibration_mm_s=2.1,
        compressor_running=True,
    )
    db.add(telemetry)
    db.flush()
    deviation = EquipmentDeviation(
        equipment_id=equipment_id,
        telemetry_id=telemetry.id,
        metric_name="temperature_c",
        observed_value=82.0,
        threshold_value=75.0,
        message="Температура выше порога",
    )
    db.add(deviation)
    db.commit()
    response = client.post(
        f"/incidents/{incident_id}/deviations",
        json={"deviation_id": deviation.id},
    )
    assert response.status_code == 204, response.text
    return deviation.id


def _analysis_json(chunk_id: int) -> str:
    return json.dumps(
        {
            "observed_facts": ["Температура превысила порог"],
            "possible_causes": [
                {
                    "text": "Возможно загрязнение масляного фильтра",
                    "source_chunk_ids": [chunk_id],
                },
            ],
            "required_checks": [
                {
                    "text": "Проверить давление масла",
                    "source_chunk_ids": [chunk_id],
                },
            ],
            "recommendations": [
                {
                    "text": "Осмотреть фильтр по инструкции",
                    "source_chunk_ids": [chunk_id],
                },
            ],
            "insufficient_data": ["Нет истории давления масла"],
            "warnings": [],
        },
        ensure_ascii=False,
    )


def _payload() -> dict:
    return {
        "query": "давление масла",
        "provider": "compatible",
        "model": "fake-model",
        "max_sources": 5,
    }


def test_incident_analysis_is_grounded_journaled_and_versioned(
    client: TestClient,
    db_session: Session,
    equipment: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = _create_incident(client, equipment["id"])
    deviation_id = _link_deviation(
        client,
        db_session,
        incident_id=incident["id"],
        equipment_id=equipment["id"],
    )
    chunk_id = _create_source(db_session, equipment)
    provider = FakeProvider(content=_analysis_json(chunk_id))
    monkeypatch.setattr(
        "app.incidents.router.build_provider",
        lambda *args, **kwargs: provider,
    )

    response = client.post(
        f"/incidents/{incident['id']}/analyses",
        json=_payload(),
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "completed"
    assert data["prompt_version"] == "incident-analysis-v1"
    assert data["llm_call_id"] > 0
    assert data["result"]["possible_causes"][0]["source_chunk_ids"] == [chunk_id]
    assert HUMAN_REVIEW_WARNING in data["result"]["warnings"]
    assert data["sources"][0]["chunk_id"] == chunk_id
    assert data["sources"][0]["citation"].startswith("KB:D")
    assert data["sources"][0]["source_uri"] == "warehouse://manuals/cooler"
    assert provider.closed is True

    assert len(provider.calls) == 1
    assert provider.calls[0][0].role == "system"
    prompt_payload = json.loads(provider.calls[0][1].content)
    assert prompt_payload["incident_context"]["equipment"]["code"] == equipment["code"]
    assert prompt_payload["incident_context"]["deviations"][0]["id"] == deviation_id
    assert (
        prompt_payload["incident_context"]["deviations"][0]["telemetry"][
            "temperature_c"
        ]
        == 82.0
    )
    assert prompt_payload["retrieved_sources"][0]["chunk_id"] == chunk_id

    call = db_session.get(LLMCall, data["llm_call_id"])
    assert call is not None
    assert call.prompt_version == "incident-analysis-v1"
    assert call.parameters == {"temperature": 0.0, "max_tokens": 1200}
    assert db_session.scalar(select(func.count()).select_from(IncidentAnalysis)) == 1
    assert (
        db_session.scalar(select(func.count()).select_from(IncidentAnalysisSource)) == 1
    )

    history = client.get(f"/incidents/{incident['id']}/analyses")
    assert history.status_code == 200
    assert history.json() == [data]


def test_analysis_without_sources_is_saved_without_calling_llm(
    client: TestClient,
    db_session: Session,
    equipment: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = _create_incident(client, equipment["id"])

    def fail_if_provider_is_built(*args, **kwargs):
        pytest.fail("Провайдер не должен создаваться без источников")

    monkeypatch.setattr(
        "app.incidents.router.build_provider",
        fail_if_provider_is_built,
    )

    response = client.post(
        f"/incidents/{incident['id']}/analyses",
        json=_payload(),
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "insufficient"
    assert data["llm_call_id"] is None
    assert data["sources"] == []
    assert data["result"]["possible_causes"] == []
    assert data["result"]["insufficient_data"]
    assert db_session.scalar(select(LLMCall)) is None


def test_analysis_rejects_hallucinated_source_but_keeps_llm_call(
    client: TestClient,
    db_session: Session,
    equipment: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = _create_incident(client, equipment["id"])
    chunk_id = _create_source(db_session, equipment)
    provider = FakeProvider(content=_analysis_json(chunk_id + 999))
    monkeypatch.setattr(
        "app.incidents.router.build_provider",
        lambda *args, **kwargs: provider,
    )

    response = client.post(
        f"/incidents/{incident['id']}/analyses",
        json=_payload(),
    )

    assert response.status_code == 502
    assert "неизвестные фрагменты" in response.json()["detail"]["message"]
    call_id = response.json()["detail"]["call_id"]
    assert db_session.get(LLMCall, call_id) is not None
    assert db_session.scalar(select(IncidentAnalysis)) is None
    assert provider.closed is True


def test_analysis_rejects_invalid_json_but_keeps_llm_call(
    client: TestClient,
    db_session: Session,
    equipment: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = _create_incident(client, equipment["id"])
    _create_source(db_session, equipment)
    provider = FakeProvider(content="not-json")
    monkeypatch.setattr(
        "app.incidents.router.build_provider",
        lambda *args, **kwargs: provider,
    )

    response = client.post(
        f"/incidents/{incident['id']}/analyses",
        json=_payload(),
    )

    assert response.status_code == 502
    assert "структуре анализа" in response.json()["detail"]["message"]
    call_id = response.json()["detail"]["call_id"]
    assert db_session.get(LLMCall, call_id) is not None
    assert db_session.scalar(select(IncidentAnalysis)) is None
    assert provider.closed is True


def test_analysis_provider_timeout_is_journaled(
    client: TestClient,
    db_session: Session,
    equipment: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = _create_incident(client, equipment["id"])
    _create_source(db_session, equipment)
    provider = FakeProvider(
        error=LLMTimeoutError("Провайдер не ответил", provider="compatible"),
    )
    monkeypatch.setattr(
        "app.incidents.router.build_provider",
        lambda *args, **kwargs: provider,
    )

    response = client.post(
        f"/incidents/{incident['id']}/analyses",
        json=_payload(),
    )

    assert response.status_code == 504
    call_id = response.json()["detail"]["call_id"]
    call = db_session.get(LLMCall, call_id)
    assert call is not None
    assert call.status == "error"
    assert call.error_type == "timeout"
    assert db_session.scalar(select(IncidentAnalysis)) is None
    assert provider.closed is True


def test_analysis_endpoints_validate_incident_and_payload(
    client: TestClient,
) -> None:
    assert client.post("/incidents/999/analyses", json=_payload()).status_code == 404
    assert client.get("/incidents/999/analyses").status_code == 404
    invalid = _payload()
    invalid["query"] = "x"
    assert client.post("/incidents/999/analyses", json=invalid).status_code == 422
