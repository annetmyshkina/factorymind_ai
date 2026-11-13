import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.core.database import SessionLocal, engine
from app.equipment.models import Equipment
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
