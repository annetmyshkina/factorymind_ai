from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge.models import KnowledgeDocumentChunk
from app.knowledge.processing import (
    CHUNK_OVERLAP_CHARS,
    MAX_CHUNK_CHARS,
    DocumentProcessingError,
    ExtractedSection,
    build_chunks,
    normalize_extracted_text,
    process_document_version,
)
from app.knowledge.schemas import KnowledgeDocumentCreate
from app.knowledge.service import add_document_version, create_document


def _stored_text_version(db: Session, content: bytes = b"maintenance guide"):
    document = create_document(
        db,
        KnowledgeDocumentCreate(
            title="Processing test manual",
            document_type="maintenance_instruction",
            source_name="Test warehouse",
        ),
    )
    return add_document_version(
        db,
        document.id,
        version="v1",
        filename="manual.txt",
        mime_type="text/plain",
        content=content,
    )


def _text_pdf(content: str) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        },
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)},
            ),
        },
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 10 100 Td ({content}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


def test_text_normalization_and_chunking_are_deterministic() -> None:
    source = "  Насос\t  включён\r\n\r\n\r\n Давление  5 бар "
    assert normalize_extracted_text(source) == "Насос включён\n\nДавление 5 бар"
    text = " ".join(f"слово-{index}" for index in range(500))
    sections = [ExtractedSection(content=text, page_number=3)]

    first = build_chunks(sections)
    second = build_chunks(sections)

    assert first == second
    assert len(first) > 1
    assert all(0 < len(chunk.content) <= MAX_CHUNK_CHARS for chunk in first)
    assert all(chunk.page_start == chunk.page_end == 3 for chunk in first)
    for previous, current in zip(first, first[1:], strict=False):
        overlap = previous.end_offset - current.start_offset
        assert 0 < overlap <= CHUNK_OVERLAP_CHARS


def test_processing_is_atomic_and_idempotent(db_session: Session) -> None:
    version = _stored_text_version(
        db_session,
        "Проверить давление масла. Заменить фильтр после остановки.".encode(),
    )

    processed, first_chunks = process_document_version(db_session, version.id)
    repeated, second_chunks = process_document_version(db_session, version.id)

    assert processed.status == repeated.status == "ready"
    assert processed.processed_at is not None
    assert [chunk.id for chunk in first_chunks] == [chunk.id for chunk in second_chunks]
    chunk_count = db_session.scalar(
        select(func.count()).select_from(KnowledgeDocumentChunk),
    )
    assert chunk_count == 1


def test_pdf_text_layer_preserves_page_number(db_session: Session) -> None:
    document = create_document(
        db_session,
        KnowledgeDocumentCreate(
            title="PDF manual",
            document_type="operation_manual",
            source_name="Test warehouse",
        ),
    )
    version = add_document_version(
        db_session,
        document.id,
        version="pdf-1",
        filename="manual.pdf",
        mime_type="application/pdf",
        content=_text_pdf("Pressure check procedure"),
    )

    processed, chunks = process_document_version(db_session, version.id)

    assert processed.status == "ready"
    assert [chunk.content for chunk in chunks] == ["Pressure check procedure"]
    assert chunks[0].page_start == chunks[0].page_end == 1


def test_scanned_pdf_is_marked_failed_without_partial_chunks(
    db_session: Session,
) -> None:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    document = create_document(
        db_session,
        KnowledgeDocumentCreate(
            title="Scanned manual",
            document_type="operation_manual",
            source_name="Test scanner",
        ),
    )
    version = add_document_version(
        db_session,
        document.id,
        version="scan-1",
        filename="scan.pdf",
        mime_type="application/pdf",
        content=output.getvalue(),
    )

    with pytest.raises(DocumentProcessingError, match="OCR"):
        process_document_version(db_session, version.id)

    db_session.refresh(version)
    assert version.status == "failed"
    assert version.processed_at is None
    assert version.processing_error is not None
    assert "OCR" in version.processing_error
    chunk_count = db_session.scalar(
        select(func.count()).select_from(KnowledgeDocumentChunk),
    )
    assert chunk_count == 0
