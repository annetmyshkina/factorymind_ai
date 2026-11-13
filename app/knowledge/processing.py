"""Извлечение и воспроизводимое разбиение технических документов."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.knowledge.models import KnowledgeDocumentChunk, KnowledgeDocumentVersion
from app.knowledge.service import KnowledgeDocumentVersionNotFoundError

CHUNKING_VERSION = "paragraph-v1"
MAX_CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 200
MAX_PDF_PAGE_STREAM_BYTES = 20 * 1024 * 1024
MAX_PDF_TOTAL_STREAM_BYTES = 50 * 1024 * 1024

_horizontal_whitespace = re.compile(r"[^\S\n]+")
_blank_lines = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")


class DocumentProcessingError(ValueError):
    """Документ не удалось безопасно преобразовать в текстовые чанки."""


@dataclass(frozen=True, slots=True)
class ExtractedSection:
    """Нормализованный текст одной страницы или всего текстового файла."""

    content: str
    page_number: int | None


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """Детерминированное представление чанка до сохранения."""

    chunk_index: int
    content: str
    checksum_sha256: str
    page_start: int | None
    page_end: int | None
    start_offset: int
    end_offset: int


def normalize_extracted_text(value: str) -> str:
    """Нормализует Unicode и пробелы, сохраняя границы абзацев."""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        _horizontal_whitespace.sub(" ", line).strip() for line in normalized.split("\n")
    ]
    normalized = "\n".join(lines)
    normalized = _blank_lines.sub("\n\n", normalized)
    return normalized.strip()


def _extract_pdf_sections(content: bytes) -> list[ExtractedSection]:
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentProcessingError("PDF защищён паролем")

        sections: list[ExtractedSection] = []
        total_stream_size = 0
        for page_number, page in enumerate(reader.pages, start=1):
            page_contents = page.get_contents()
            if page_contents is not None:
                stream_size = len(page_contents.get_data())
                total_stream_size += stream_size
                if stream_size > MAX_PDF_PAGE_STREAM_BYTES:
                    raise DocumentProcessingError(
                        f"Поток страницы {page_number} превышает безопасный лимит",
                    )
                if total_stream_size > MAX_PDF_TOTAL_STREAM_BYTES:
                    raise DocumentProcessingError(
                        "Суммарный поток PDF превышает безопасный лимит",
                    )
            page_text = normalize_extracted_text(page.extract_text() or "")
            if page_text:
                sections.append(
                    ExtractedSection(
                        content=page_text,
                        page_number=page_number,
                    ),
                )
    except DocumentProcessingError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise DocumentProcessingError("Не удалось прочитать PDF") from exc

    if not sections:
        raise DocumentProcessingError(
            "PDF не содержит извлекаемого текста; для скана требуется OCR",
        )
    return sections


def extract_sections(
    mime_type: str,
    content: bytes,
) -> list[ExtractedSection]:
    """Извлекает страницы PDF либо единый раздел UTF-8 текста."""
    if mime_type == "application/pdf":
        return _extract_pdf_sections(content)
    if mime_type in {"text/plain", "text/markdown"}:
        try:
            extracted = normalize_extracted_text(content.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise DocumentProcessingError(
                "Текстовый документ должен быть в UTF-8",
            ) from exc
        if not extracted:
            raise DocumentProcessingError("Документ не содержит текста")
        return [ExtractedSection(content=extracted, page_number=None)]
    raise DocumentProcessingError(f"Неподдерживаемый MIME-тип: {mime_type}")


def _choose_chunk_end(text: str, start: int, hard_end: int) -> int:
    if hard_end >= len(text):
        return len(text)
    minimum = start + (MAX_CHUNK_CHARS // 2)
    for separator in ("\n\n", ". ", "; ", "\n", " "):
        boundary = text.rfind(separator, minimum, hard_end)
        if boundary >= minimum:
            return boundary + len(separator)
    return hard_end


def _chunk_section(
    section: ExtractedSection,
    *,
    first_index: int,
    document_offset: int,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    text = section.content
    start = 0
    while start < len(text):
        hard_end = min(start + MAX_CHUNK_CHARS, len(text))
        end = _choose_chunk_end(text, start, hard_end)
        raw_chunk = text[start:end]
        leading = len(raw_chunk) - len(raw_chunk.lstrip())
        trailing = len(raw_chunk) - len(raw_chunk.rstrip())
        actual_start = start + leading
        actual_end = end - trailing
        chunk_content = text[actual_start:actual_end]
        if chunk_content:
            drafts.append(
                ChunkDraft(
                    chunk_index=first_index + len(drafts),
                    content=chunk_content,
                    checksum_sha256=sha256(chunk_content.encode()).hexdigest(),
                    page_start=section.page_number,
                    page_end=section.page_number,
                    start_offset=document_offset + actual_start,
                    end_offset=document_offset + actual_end,
                ),
            )
        if end >= len(text):
            break
        next_start = max(actual_end - CHUNK_OVERLAP_CHARS, actual_start + 1)
        if next_start <= start:
            next_start = end
        start = next_start
    return drafts


def build_chunks(sections: list[ExtractedSection]) -> list[ChunkDraft]:
    """Создаёт стабильные чанки, не объединяя разные PDF-страницы."""
    chunks: list[ChunkDraft] = []
    document_offset = 0
    for section in sections:
        section_chunks = _chunk_section(
            section,
            first_index=len(chunks),
            document_offset=document_offset,
        )
        chunks.extend(section_chunks)
        document_offset += len(section.content) + 2
    if not chunks:
        raise DocumentProcessingError("После обработки не осталось текстовых чанков")
    return chunks


def _mark_processing_failed(
    db: Session,
    document_version_id: int,
    error: DocumentProcessingError,
) -> None:
    db.rollback()
    version = db.get(KnowledgeDocumentVersion, document_version_id)
    if version is None:
        return
    version.status = "failed"
    version.processing_error = str(error)[:2000]
    version.processed_at = None
    db.commit()


def process_document_version(
    db: Session,
    document_version_id: int,
) -> tuple[KnowledgeDocumentVersion, list[KnowledgeDocumentChunk]]:
    """Атомарно извлекает текст и заменяет чанки одной версии."""
    version = db.scalar(
        select(KnowledgeDocumentVersion)
        .where(KnowledgeDocumentVersion.id == document_version_id)
        .with_for_update(),
    )
    if version is None:
        db.rollback()
        raise KnowledgeDocumentVersionNotFoundError

    existing_chunks = list(
        db.scalars(
            select(KnowledgeDocumentChunk)
            .where(
                KnowledgeDocumentChunk.document_version_id == document_version_id,
            )
            .order_by(KnowledgeDocumentChunk.chunk_index),
        ),
    )
    if version.status == "ready" and existing_chunks:
        db.rollback()
        return version, existing_chunks

    version.status = "processing"
    version.processing_error = None
    version.processed_at = None
    db.flush()

    try:
        drafts = build_chunks(extract_sections(version.mime_type, version.content))
        db.execute(
            delete(KnowledgeDocumentChunk).where(
                KnowledgeDocumentChunk.document_version_id == document_version_id,
            ),
        )
        chunks = [
            KnowledgeDocumentChunk(
                document_version_id=document_version_id,
                chunk_index=draft.chunk_index,
                content=draft.content,
                checksum_sha256=draft.checksum_sha256,
                chunking_version=CHUNKING_VERSION,
                page_start=draft.page_start,
                page_end=draft.page_end,
                start_offset=draft.start_offset,
                end_offset=draft.end_offset,
            )
            for draft in drafts
        ]
        db.add_all(chunks)
        version.status = "ready"
        version.processing_error = None
        version.processed_at = datetime.now(UTC)
        db.commit()
        for chunk in chunks:
            db.refresh(chunk)
        db.refresh(version)
        return version, chunks
    except DocumentProcessingError as exc:
        _mark_processing_failed(db, document_version_id, exc)
        raise
    except SQLAlchemyError:
        db.rollback()
        raise
    except Exception as exc:
        error = DocumentProcessingError("Не удалось обработать документ")
        _mark_processing_failed(db, document_version_id, error)
        raise error from exc
