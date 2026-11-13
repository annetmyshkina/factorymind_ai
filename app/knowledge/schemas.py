"""API-контракты каталога технической документации."""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

DocumentType = Literal[
    "operation_manual",
    "maintenance_instruction",
    "repair_instruction",
    "process_regulation",
    "safety_instruction",
    "other",
]
DocumentVersionStatus = Literal["uploaded", "processing", "ready", "failed"]


class KnowledgeDocumentCreate(BaseModel):
    """Метаданные принимаемого технического документа."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    document_type: DocumentType
    description: str | None = None
    language: str = Field(default="ru", min_length=2, max_length=10)
    source_name: str = Field(min_length=1, max_length=200)


class KnowledgeDocumentResponse(BaseModel):
    """Карточка логического документа без содержимого файла."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    document_type: DocumentType
    description: str | None
    language: str
    source_name: str
    created_at: AwareDatetime


class KnowledgeDocumentVersionResponse(BaseModel):
    """Метаданные одной неизменяемой версии документа."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version: str
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    source_uri: str | None
    status: DocumentVersionStatus
    processing_error: str | None
    processed_at: AwareDatetime | None
    is_current: bool
    created_at: AwareDatetime


class KnowledgeApplicabilityCreate(BaseModel):
    """Привязка версии ровно к одной области применения."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    equipment_id: int | None = Field(default=None, gt=0)
    equipment_type: str | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> Self:
        if (self.equipment_id is None) == (self.equipment_type is None):
            raise ValueError(
                "Укажите ровно одно из полей: equipment_id или equipment_type",
            )
        return self


class KnowledgeApplicabilityResponse(BaseModel):
    """Сохранённая область применения версии документа."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_version_id: int
    equipment_id: int | None
    equipment_type: str | None
    notes: str | None
    created_at: AwareDatetime


class KnowledgeDocumentVersionDetail(KnowledgeDocumentVersionResponse):
    """Версия документа со всеми явными областями применения."""

    applicability: list[KnowledgeApplicabilityResponse]


class KnowledgeDocumentDetail(KnowledgeDocumentResponse):
    """Документ, его версии и привязки без бинарного содержимого."""

    versions: list[KnowledgeDocumentVersionDetail]


class KnowledgeChunkResponse(BaseModel):
    """Сохранённый фрагмент текста с координатами источника."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_version_id: int
    chunk_index: int
    content: str
    checksum_sha256: str
    chunking_version: str
    page_start: int | None
    page_end: int | None
    start_offset: int
    end_offset: int
    created_at: AwareDatetime


class KnowledgeProcessingResponse(BaseModel):
    """Результат детерминированной обработки версии."""

    document_version_id: int
    status: DocumentVersionStatus
    processed_at: AwareDatetime | None
    chunk_count: int
    chunks: list[KnowledgeChunkResponse]


class KnowledgeSearchResult(BaseModel):
    """Релевантный чанк с данными для проверяемой цитаты."""

    chunk_id: int
    chunk_index: int
    content: str
    checksum_sha256: str
    page_start: int | None
    page_end: int | None
    score: float = Field(ge=0)
    document_id: int
    document_title: str
    document_type: DocumentType
    source_name: str
    document_version_id: int
    document_version: str
    source_uri: str | None
