"""Модели документов, версий и применимости базы знаний."""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import UTCDateTime

DOCUMENT_TYPES = (
    "operation_manual",
    "maintenance_instruction",
    "repair_instruction",
    "process_regulation",
    "safety_instruction",
    "other",
)
VERSION_STATUSES = ("uploaded", "processing", "ready", "failed")

_chunk_search_index = Index(
    "ix_knowledge_document_chunks_search",
    text("to_tsvector('simple', content)"),
    postgresql_using="gin",
).ddl_if(dialect="postgresql")


class KnowledgeDocument(Base):
    """Логический технический документ с неизменяемыми версиями."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ("
            "'operation_manual', 'maintenance_instruction', "
            "'repair_instruction', 'process_regulation', "
            "'safety_instruction', 'other')",
            name="ck_knowledge_documents_type",
        ),
        Index("ix_knowledge_documents_created_at", "created_at"),
        Index("ix_knowledge_documents_document_type", "document_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(
        String(10),
        default="ru",
        server_default="ru",
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeDocumentVersion(Base):
    """Неизменяемый файл одной версии документа."""

    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')",
            name="ck_knowledge_document_versions_status",
        ),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 10485760",
            name="ck_knowledge_document_versions_size",
        ),
        CheckConstraint(
            "length(checksum_sha256) = 64",
            name="ck_knowledge_document_versions_checksum",
        ),
        CheckConstraint(
            "(status = 'failed' AND processing_error IS NOT NULL) "
            "OR (status <> 'failed' AND processing_error IS NULL)",
            name="ck_knowledge_document_versions_error_state",
        ),
        CheckConstraint(
            "status <> 'ready' OR processed_at IS NOT NULL",
            name="ck_knowledge_document_versions_processed_state",
        ),
        UniqueConstraint(
            "document_id",
            "version",
            name="uq_knowledge_document_versions_document_version",
        ),
        UniqueConstraint(
            "document_id",
            "checksum_sha256",
            name="uq_knowledge_document_versions_document_checksum",
        ),
        Index(
            "uq_knowledge_document_versions_current",
            "document_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
        Index("ix_knowledge_document_versions_status", "status"),
        Index("ix_knowledge_document_versions_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="uploaded",
        server_default="uploaded",
        nullable=False,
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    is_current: Mapped[bool] = mapped_column(
        default=True,
        server_default=text("true"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeDocumentChunk(Base):
    """Воспроизводимый фрагмент извлечённого текста для retrieval."""

    __tablename__ = "knowledge_document_chunks"
    __table_args__ = (
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_document_chunks_index",
        ),
        CheckConstraint(
            "length(content) > 0",
            name="ck_knowledge_document_chunks_content",
        ),
        CheckConstraint(
            "length(checksum_sha256) = 64",
            name="ck_knowledge_document_chunks_checksum",
        ),
        CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_knowledge_document_chunks_offsets",
        ),
        CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) "
            "OR (page_start > 0 AND page_end >= page_start)",
            name="ck_knowledge_document_chunks_pages",
        ),
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_knowledge_document_chunks_version_index",
        ),
        Index(
            "ix_knowledge_document_chunks_version",
            "document_version_id",
            "chunk_index",
        ),
        _chunk_search_index,
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunking_version: Mapped[str] = mapped_column(
        String(30),
        default="paragraph-v1",
        server_default="paragraph-v1",
        nullable=False,
    )
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeDocumentApplicability(Base):
    """Явная применимость версии к типу или единице оборудования."""

    __tablename__ = "knowledge_document_applicability"
    __table_args__ = (
        CheckConstraint(
            "(equipment_id IS NOT NULL AND equipment_type IS NULL) "
            "OR (equipment_id IS NULL AND equipment_type IS NOT NULL)",
            name="ck_knowledge_document_applicability_target",
        ),
        CheckConstraint(
            "equipment_type IS NULL OR length(trim(equipment_type)) > 0",
            name="ck_knowledge_document_applicability_equipment_type",
        ),
        UniqueConstraint(
            "document_version_id",
            "equipment_id",
            name="uq_knowledge_document_applicability_equipment",
        ),
        UniqueConstraint(
            "document_version_id",
            "equipment_type",
            name="uq_knowledge_document_applicability_type",
        ),
        Index(
            "ix_knowledge_document_applicability_type",
            "equipment_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    equipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    equipment_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
