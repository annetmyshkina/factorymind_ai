from hashlib import sha256

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.equipment.models import Equipment
from app.knowledge.models import (
    KnowledgeDocumentApplicability,
    KnowledgeDocumentVersion,
)
from app.knowledge.schemas import (
    KnowledgeApplicabilityCreate,
    KnowledgeDocumentCreate,
)
from app.knowledge.service import (
    MAX_DOCUMENT_SIZE_BYTES,
    InvalidKnowledgeFileError,
    KnowledgeConflictError,
    KnowledgeEquipmentNotFoundError,
    KnowledgeEquipmentTypeNotFoundError,
    add_applicability,
    add_document_version,
    create_document,
    get_document_detail,
    get_document_version,
    list_documents,
    remove_applicability,
    validate_document_file,
)


def _equipment(db: Session, *, code: str = "COOLER-KB") -> Equipment:
    equipment = Equipment(
        code=code,
        name="Knowledge test cooler",
        equipment_type="cooling_unit",
        location="Test shop",
    )
    db.add(equipment)
    db.commit()
    db.refresh(equipment)
    return equipment


def _document(db: Session):
    return create_document(
        db,
        KnowledgeDocumentCreate(
            title="Cooling unit manual",
            document_type="operation_manual",
            description="Synthetic documentation for tests",
            language="ru",
            source_name="FactoryMind demo warehouse",
        ),
    )


def _text_version(
    db: Session,
    document_id: int,
    *,
    version: str = "v1",
    content: bytes = b"Cooling unit maintenance instructions",
):
    return add_document_version(
        db,
        document_id,
        version=version,
        filename="manual.md",
        mime_type="text/markdown",
        content=content,
        source_uri="warehouse://manuals/cooling-unit",
    )


def test_document_versions_are_immutable_and_latest_is_current(
    db_session: Session,
) -> None:
    equipment = _equipment(db_session)
    document = _document(db_session)
    first = _text_version(db_session, document.id)
    first_link = add_applicability(
        db_session,
        first.id,
        KnowledgeApplicabilityCreate(equipment_type="cooling_unit"),
    )

    second = _text_version(
        db_session,
        document.id,
        version="v2",
        content=b"Updated cooling unit maintenance instructions",
    )
    db_session.refresh(first)
    assert first.is_current is False
    assert second.is_current is True
    assert second.checksum_sha256 == sha256(second.content).hexdigest()
    assert second.size_bytes == len(second.content)
    assert get_document_version(db_session, first.id).content == first.content

    # Применимость старой версии не переносится на новую неявно.
    assert list_documents(db_session, equipment_id=equipment.id) == []
    second_link = add_applicability(
        db_session,
        second.id,
        KnowledgeApplicabilityCreate(
            equipment_id=equipment.id,
            notes="Checked against the demo inventory",
        ),
    )
    assert [
        item.id for item in list_documents(db_session, equipment_id=equipment.id)
    ] == [
        document.id,
    ]

    detail = get_document_detail(db_session, document.id)
    assert [item.version for item in detail.versions] == ["v2", "v1"]
    assert [item.id for item in detail.versions[0].applicability] == [
        second_link.id,
    ]
    assert [item.id for item in detail.versions[1].applicability] == [first_link.id]
    assert "content" not in detail.model_dump()["versions"][0]


def test_duplicate_version_rolls_back_current_version_change(
    db_session: Session,
) -> None:
    document = _document(db_session)
    first = _text_version(db_session, document.id)

    with pytest.raises(KnowledgeConflictError):
        _text_version(
            db_session,
            document.id,
            version="v1",
            content=b"Different content with duplicate version",
        )

    db_session.expire_all()
    saved = db_session.get(KnowledgeDocumentVersion, first.id)
    assert saved is not None
    assert saved.is_current is True
    assert list(db_session.scalars(select(KnowledgeDocumentVersion))) == [saved]

    with pytest.raises(KnowledgeConflictError):
        _text_version(
            db_session,
            document.id,
            version="v2",
            content=first.content,
        )


@pytest.mark.parametrize(
    ("filename", "mime_type", "content", "message"),
    [
        ("empty.txt", "text/plain", b"", "пуст"),
        ("manual.exe", "application/octet-stream", b"data", "PDF, TXT"),
        ("manual.pdf", "text/plain", b"%PDF-1.4", "MIME"),
        ("manual.pdf", "application/pdf", b"not pdf", "сигнатуру"),
        ("manual.txt", "text/plain", b"\xff", "UTF-8"),
    ],
)
def test_document_file_validation(
    filename: str,
    mime_type: str,
    content: bytes,
    message: str,
) -> None:
    with pytest.raises(InvalidKnowledgeFileError, match=message):
        validate_document_file(filename, mime_type, content)


def test_document_file_size_limit() -> None:
    with pytest.raises(InvalidKnowledgeFileError, match="10 МБ"):
        validate_document_file(
            "large.txt",
            "text/plain",
            b"x" * (MAX_DOCUMENT_SIZE_BYTES + 1),
        )


def test_applicability_requires_exactly_one_existing_target(
    db_session: Session,
) -> None:
    document = _document(db_session)
    version = _text_version(db_session, document.id)

    with pytest.raises(ValidationError, match="ровно одно"):
        KnowledgeApplicabilityCreate()
    with pytest.raises(ValidationError, match="ровно одно"):
        KnowledgeApplicabilityCreate(
            equipment_id=1,
            equipment_type="cooling_unit",
        )
    with pytest.raises(KnowledgeEquipmentNotFoundError):
        add_applicability(
            db_session,
            version.id,
            KnowledgeApplicabilityCreate(equipment_id=999),
        )
    with pytest.raises(KnowledgeEquipmentTypeNotFoundError):
        add_applicability(
            db_session,
            version.id,
            KnowledgeApplicabilityCreate(equipment_type="unknown"),
        )

    equipment = _equipment(db_session)
    link = add_applicability(
        db_session,
        version.id,
        KnowledgeApplicabilityCreate(equipment_id=equipment.id),
    )
    with pytest.raises(KnowledgeConflictError):
        add_applicability(
            db_session,
            version.id,
            KnowledgeApplicabilityCreate(equipment_id=equipment.id),
        )
    remove_applicability(db_session, link.id)
    assert db_session.scalar(select(KnowledgeDocumentApplicability)) is None


def test_catalog_filters_by_type_and_language(db_session: Session) -> None:
    first = _document(db_session)
    second = create_document(
        db_session,
        KnowledgeDocumentCreate(
            title="Safety",
            document_type="safety_instruction",
            language="en",
            source_name="Demo warehouse",
        ),
    )

    assert [item.id for item in list_documents(db_session, language="ru")] == [
        first.id,
    ]
    assert [
        item.id
        for item in list_documents(
            db_session,
            document_type="safety_instruction",
        )
    ] == [second.id]
