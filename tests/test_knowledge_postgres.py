import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text

from app.ai.contracts import ChatMessage, LLMResponse
from app.ai.models import LLMCall
from app.ai.providers.base import LLMProvider
from app.core.database import SessionLocal, engine
from app.equipment.models import Equipment
from app.incidents.analysis import (
    execute_incident_analysis,
    prepare_incident_analysis,
)
from app.incidents.models import Incident, IncidentAnalysisSource
from app.incidents.service import create_incident
from app.knowledge.models import KnowledgeDocument, KnowledgeDocumentVersion
from app.knowledge.processing import process_document_version
from app.knowledge.retrieval import search_knowledge
from app.knowledge.schemas import (
    KnowledgeApplicabilityCreate,
    KnowledgeDocumentCreate,
)
from app.knowledge.service import (
    add_applicability,
    add_document_version,
    create_document,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_INTEGRATION") != "1",
    reason="Интеграционные тесты базы знаний требуют PostgreSQL",
)


class _PostgresFakeProvider(LLMProvider):
    name = "compatible"
    model = "postgres-test-model"

    def __init__(self, content: str) -> None:
        self.content = content

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            provider=self.name,
            model=self.model,
            content=self.content,
            latency_ms=1,
        )

    def close(self) -> None:
        pass


def test_parallel_version_uploads_leave_one_current_version() -> None:
    assert engine.dialect.name == "postgresql"
    suffix = uuid4().hex
    with SessionLocal() as db:
        document = create_document(
            db,
            KnowledgeDocumentCreate(
                title=f"Concurrent manual {suffix}",
                document_type="operation_manual",
                source_name="PostgreSQL integration test",
            ),
        )
        document_id = document.id

    barrier = Barrier(2)

    def upload(version: str) -> int:
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            barrier.wait(timeout=5)
            stored = add_document_version(
                db,
                document_id,
                version=version,
                filename=f"manual-{version}.txt",
                mime_type="text/plain",
                content=f"Content of {version}".encode(),
            )
            return stored.id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            version_ids = [
                future.result(timeout=10)
                for future in (
                    executor.submit(upload, "v1"),
                    executor.submit(upload, "v2"),
                )
            ]

        with SessionLocal() as db:
            versions = list(
                db.scalars(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.document_id == document_id,
                    ),
                ),
            )
            current_count = db.scalar(
                select(func.count())
                .select_from(KnowledgeDocumentVersion)
                .where(
                    KnowledgeDocumentVersion.document_id == document_id,
                    KnowledgeDocumentVersion.is_current.is_(True),
                ),
            )

        assert {item.id for item in versions} == set(version_ids)
        assert current_count == 1
    finally:
        with SessionLocal() as db:
            document = db.get(KnowledgeDocument, document_id)
            if document is not None:
                db.delete(document)
                db.commit()


def test_postgresql_full_text_search_filters_by_applicability() -> None:
    assert engine.dialect.name == "postgresql"
    suffix = uuid4().hex
    with SessionLocal() as db:
        equipment = Equipment(
            code=f"KB-FTS-{suffix}",
            name="PostgreSQL FTS cooler",
            equipment_type=f"cooler-{suffix}",
            location="Integration test",
        )
        db.add(equipment)
        db.commit()
        db.refresh(equipment)
        equipment_id = equipment.id

        document = create_document(
            db,
            KnowledgeDocumentCreate(
                title=f"FTS manual {suffix}",
                document_type="maintenance_instruction",
                source_name="PostgreSQL integration test",
            ),
        )
        document_id = document.id
        version = add_document_version(
            db,
            document.id,
            version="v1",
            filename="manual.txt",
            mime_type="text/plain",
            content="Проверить давление масла и состояние фильтра.".encode(),
        )
        add_applicability(
            db,
            version.id,
            KnowledgeApplicabilityCreate(equipment_id=equipment.id),
        )
        process_document_version(db, version.id)

        results = search_knowledge(
            db,
            query="давление масла",
            equipment_id=equipment.id,
        )
        index_exists = db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                "WHERE indexname = 'ix_knowledge_document_chunks_search')",
            ),
        )

    try:
        assert index_exists is True
        assert len(results) == 1
        assert results[0].document_id == document_id
        assert results[0].score > 0
    finally:
        with SessionLocal() as db:
            document = db.get(KnowledgeDocument, document_id)
            if document is not None:
                db.delete(document)
            equipment = db.get(Equipment, equipment_id)
            if equipment is not None:
                db.delete(equipment)
            db.commit()


def test_postgresql_persists_analysis_with_exact_source_link() -> None:
    assert engine.dialect.name == "postgresql"
    suffix = uuid4().hex
    call_id: int | None = None
    with SessionLocal() as db:
        equipment = Equipment(
            code=f"KB-ANALYSIS-{suffix}",
            name="PostgreSQL analysis cooler",
            equipment_type=f"analysis-cooler-{suffix}",
            location="Integration test",
        )
        db.add(equipment)
        db.commit()
        db.refresh(equipment)
        equipment_id = equipment.id

        incident = create_incident(
            db,
            equipment_id=equipment.id,
            title="Oil pressure incident",
            severity="high",
        )
        incident_id = incident.id
        document = create_document(
            db,
            KnowledgeDocumentCreate(
                title=f"Analysis manual {suffix}",
                document_type="maintenance_instruction",
                source_name="PostgreSQL integration test",
            ),
        )
        document_id = document.id
        version = add_document_version(
            db,
            document.id,
            version="v1",
            filename="analysis.txt",
            mime_type="text/plain",
            content="Проверить давление масла и фильтр.".encode(),
        )
        add_applicability(
            db,
            version.id,
            KnowledgeApplicabilityCreate(equipment_id=equipment.id),
        )
        _, chunks = process_document_version(db, version.id)
        chunk_id = chunks[0].id

        prepared = prepare_incident_analysis(
            db,
            incident_id=incident.id,
            query="давление масла",
            max_sources=5,
        )
        provider = _PostgresFakeProvider(
            json.dumps(
                {
                    "observed_facts": ["Зафиксирован инцидент"],
                    "possible_causes": [],
                    "required_checks": [
                        {
                            "text": "Проверить давление масла",
                            "source_chunk_ids": [chunk_id],
                        },
                    ],
                    "recommendations": [],
                    "insufficient_data": [],
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
        )
        call, analysis = execute_incident_analysis(db, provider, prepared)
        call_id = call.id
        link_count = db.scalar(
            select(func.count()).select_from(IncidentAnalysisSource),
        )

    try:
        assert analysis is not None
        assert analysis.status == "completed"
        assert analysis.sources[0].chunk_id == chunk_id
        assert link_count == 1
    finally:
        with SessionLocal() as db:
            db.execute(delete(Incident).where(Incident.id == incident_id))
            db.commit()
            if call_id is not None:
                db.execute(delete(LLMCall).where(LLMCall.id == call_id))
            db.execute(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.id == document_id,
                ),
            )
            db.execute(delete(Equipment).where(Equipment.id == equipment_id))
            db.commit()
