import os
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.core.database import SessionLocal, engine
from app.equipment.models import Equipment
from app.evaluation.rag import evaluate_rag_suite, load_rag_benchmark
from app.incidents.feedback import (
    confirm_incident_resolution,
    revoke_incident_resolution,
)
from app.incidents.schemas import IncidentResolutionCreate
from app.incidents.service import change_status, create_incident
from app.knowledge.models import KnowledgeDocument
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

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_INTEGRATION") != "1",
    reason="RAG benchmark требует изолированный PostgreSQL-корпус",
)

BENCHMARK_PATH = Path("benchmarks/rag/retrieval-v1.json")
EQUIPMENT_CODES = (
    "BENCH-RAG-COMPRESSOR-V1",
    "BENCH-RAG-CONVEYOR-V1",
)
DOCUMENT_TITLES = (
    "Benchmark: инструкция компрессора",
    "Benchmark: инструкция конвейера",
)


def _cleanup_benchmark_corpus() -> None:
    with SessionLocal() as db:
        db.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.title.in_(DOCUMENT_TITLES),
            ),
        )
        db.execute(delete(Equipment).where(Equipment.code.in_(EQUIPMENT_CODES)))
        db.commit()


def _equipment(db, *, code: str, equipment_type: str) -> Equipment:
    equipment = Equipment(
        code=code,
        name=code,
        equipment_type=equipment_type,
        location="RAG benchmark",
    )
    db.add(equipment)
    db.commit()
    db.refresh(equipment)
    return equipment


def _ready_document(
    db,
    *,
    title: str,
    content: str,
    equipment_id: int,
) -> None:
    document = create_document(
        db,
        KnowledgeDocumentCreate(
            title=title,
            document_type="maintenance_instruction",
            source_name="RAG benchmark fixture",
        ),
    )
    version = add_document_version(
        db,
        document.id,
        version="v1",
        filename="benchmark.txt",
        mime_type="text/plain",
        content=content.encode(),
    )
    add_applicability(
        db,
        version.id,
        KnowledgeApplicabilityCreate(equipment_id=equipment_id),
    )
    process_document_version(db, version.id)


def _resolved_incident(
    db,
    *,
    equipment_id: int,
    title: str,
    cause: str,
) -> int:
    incident = create_incident(
        db,
        equipment_id=equipment_id,
        title=title,
        severity="high",
    )
    change_status(db, incident, "in_progress")
    change_status(db, incident, "resolved")
    db.commit()
    confirm_incident_resolution(
        db,
        incident_id=incident.id,
        payload=IncidentResolutionCreate(
            checks_performed=[f"Проверена причина: {cause}"],
            confirmed_cause=cause,
            actions_taken=["Выполнено корректирующее действие"],
            outcome="Оборудование работает штатно",
            actor="rag-benchmark",
        ),
    )
    return incident.id


def test_versioned_rag_benchmark_on_isolated_postgresql() -> None:
    assert engine.dialect.name == "postgresql"
    _cleanup_benchmark_corpus()
    try:
        with SessionLocal() as db:
            compressor = _equipment(
                db,
                code=EQUIPMENT_CODES[0],
                equipment_type="benchmark-compressor",
            )
            conveyor = _equipment(
                db,
                code=EQUIPMENT_CODES[1],
                equipment_type="benchmark-conveyor",
            )
            _ready_document(
                db,
                title=DOCUMENT_TITLES[0],
                content="При перегреве проверить давление масла и масляный фильтр.",
                equipment_id=compressor.id,
            )
            _ready_document(
                db,
                title=DOCUMENT_TITLES[1],
                content="Проверить приводной ремень и натяжной ролик.",
                equipment_id=conveyor.id,
            )
            create_incident(
                db,
                equipment_id=compressor.id,
                title="Текущий перегрев компрессора",
                severity="critical",
            )
            _resolved_incident(
                db,
                equipment_id=compressor.id,
                title="Историческое падение давления масла",
                cause="Недостаточное давление масла",
            )
            _resolved_incident(
                db,
                equipment_id=conveyor.id,
                title="Проскальзывание конвейера",
                cause="Ослаблен приводной ремень",
            )
            revoked_id = _resolved_incident(
                db,
                equipment_id=compressor.id,
                title="Ошибочная кавитация",
                cause="Кавитация",
            )
            revoke_incident_resolution(
                db,
                incident_id=revoked_id,
                actor="rag-benchmark",
                reason="Причина не подтвердилась",
            )

            suite = load_rag_benchmark(BENCHMARK_PATH)
            report = evaluate_rag_suite(db, suite)
            db.rollback()

        reports = {item.case_id: item for item in report.cases}
        assert report.evaluator_version == "rag-retrieval-deterministic-v1"
        relevant = reports["oil-pressure-relevant-sources"]
        assert relevant.documents.hit_at_k is True
        assert relevant.documents.recall_at_k == 1
        assert relevant.documents.reciprocal_rank == 1
        assert relevant.experiences.hit_at_k is True
        assert relevant.experiences.recall_at_k == 1
        assert relevant.experiences.reciprocal_rank == 1

        foreign = reports["foreign-equipment-isolation"]
        assert foreign.documents.exclusion_pass is True
        assert foreign.experiences.exclusion_pass is True

        revoked = reports["revoked-experience-exclusion"]
        assert revoked.documents.exclusion_pass is True
        assert revoked.experiences.exclusion_pass is True

        assert report.document_summary.hit_rate == 1
        assert report.document_summary.mean_precision_at_k == pytest.approx(0.2)
        assert report.document_summary.mean_recall_at_k == 1
        assert report.document_summary.mean_reciprocal_rank == 1
        assert report.document_summary.exclusion_pass_rate == 1
        assert report.experience_summary.mean_precision_at_k == pytest.approx(1 / 3)
        assert report.experience_summary.exclusion_pass_rate == 1
        assert "total_score" not in report.model_dump()
    finally:
        _cleanup_benchmark_corpus()
