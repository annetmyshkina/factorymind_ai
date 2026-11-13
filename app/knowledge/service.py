"""Приём, каталогизация и выдача технических документов."""

from hashlib import sha256

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.equipment.models import Equipment
from app.knowledge.models import (
    KnowledgeDocument,
    KnowledgeDocumentApplicability,
    KnowledgeDocumentVersion,
)
from app.knowledge.schemas import (
    DocumentType,
    KnowledgeApplicabilityCreate,
    KnowledgeApplicabilityResponse,
    KnowledgeDocumentCreate,
    KnowledgeDocumentDetail,
    KnowledgeDocumentResponse,
    KnowledgeDocumentVersionDetail,
    KnowledgeDocumentVersionResponse,
)

MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_FILE_TYPES = {
    ".pdf": frozenset({"application/pdf"}),
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/plain"}),
    ".markdown": frozenset({"text/markdown", "text/plain"}),
}


class KnowledgeDocumentNotFoundError(LookupError):
    """Логический документ не найден."""


class KnowledgeDocumentVersionNotFoundError(LookupError):
    """Версия документа не найдена."""


class KnowledgeApplicabilityNotFoundError(LookupError):
    """Связь применимости не найдена."""


class KnowledgeEquipmentNotFoundError(LookupError):
    """Указанное оборудование не зарегистрировано."""


class KnowledgeEquipmentTypeNotFoundError(LookupError):
    """Указанный тип оборудования отсутствует в системе."""


class KnowledgeConflictError(ValueError):
    """Версия файла или область применения уже существует."""


class InvalidKnowledgeFileError(ValueError):
    """Загружаемый файл не соответствует контракту базы знаний."""


def _safe_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not normalized:
        raise InvalidKnowledgeFileError("Имя файла не задано")
    if len(normalized) > 255:
        raise InvalidKnowledgeFileError("Имя файла длиннее 255 символов")
    return normalized


def validate_document_file(
    filename: str,
    mime_type: str | None,
    content: bytes,
) -> tuple[str, str]:
    """Проверяет размер, расширение, MIME и минимальную сигнатуру файла."""
    safe_name = _safe_filename(filename)
    if not content:
        raise InvalidKnowledgeFileError("Файл пуст")
    if len(content) > MAX_DOCUMENT_SIZE_BYTES:
        raise InvalidKnowledgeFileError("Размер файла превышает 10 МБ")

    suffix = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    allowed_mime_types = ALLOWED_FILE_TYPES.get(suffix)
    if allowed_mime_types is None:
        raise InvalidKnowledgeFileError("Поддерживаются только PDF, TXT и Markdown")

    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime not in allowed_mime_types:
        raise InvalidKnowledgeFileError(
            "MIME-тип файла не соответствует его расширению",
        )

    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise InvalidKnowledgeFileError("Файл не содержит сигнатуру PDF")
    if suffix != ".pdf":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidKnowledgeFileError(
                "Текстовый документ должен быть в UTF-8",
            ) from exc
    return safe_name, normalized_mime


def create_document(
    db: Session,
    payload: KnowledgeDocumentCreate,
) -> KnowledgeDocument:
    """Создаёт карточку логического документа."""
    document = KnowledgeDocument(**payload.model_dump())
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def add_document_version(
    db: Session,
    document_id: int,
    *,
    version: str,
    filename: str,
    mime_type: str | None,
    content: bytes,
    source_uri: str | None = None,
) -> KnowledgeDocumentVersion:
    """Атомарно добавляет неизменяемую версию и делает её текущей."""
    version = version.strip()
    if not version or len(version) > 50:
        raise InvalidKnowledgeFileError("Версия должна содержать от 1 до 50 символов")
    if source_uri is not None:
        source_uri = source_uri.strip() or None
        if source_uri is not None and len(source_uri) > 500:
            raise InvalidKnowledgeFileError("Ссылка на источник длиннее 500 символов")
    safe_name, normalized_mime = validate_document_file(
        filename,
        mime_type,
        content,
    )

    document = db.scalar(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .with_for_update(),
    )
    if document is None:
        db.rollback()
        raise KnowledgeDocumentNotFoundError

    db.execute(
        update(KnowledgeDocumentVersion)
        .where(
            KnowledgeDocumentVersion.document_id == document_id,
            KnowledgeDocumentVersion.is_current.is_(True),
        )
        .values(is_current=False),
    )
    stored_version = KnowledgeDocumentVersion(
        document_id=document_id,
        version=version,
        original_filename=safe_name,
        mime_type=normalized_mime,
        size_bytes=len(content),
        checksum_sha256=sha256(content).hexdigest(),
        content=content,
        source_uri=source_uri,
        status="uploaded",
        is_current=True,
    )
    db.add(stored_version)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise KnowledgeConflictError(
            "Такая версия или такой файл уже добавлены к документу",
        ) from None
    db.refresh(stored_version)
    return stored_version


def add_applicability(
    db: Session,
    document_version_id: int,
    payload: KnowledgeApplicabilityCreate,
) -> KnowledgeDocumentApplicability:
    """Связывает версию с существующим типом или единицей оборудования."""
    if db.get(KnowledgeDocumentVersion, document_version_id) is None:
        raise KnowledgeDocumentVersionNotFoundError

    if payload.equipment_id is not None:
        if db.get(Equipment, payload.equipment_id) is None:
            raise KnowledgeEquipmentNotFoundError
    else:
        equipment_type = payload.equipment_type
        exists = db.scalar(
            select(Equipment.id)
            .where(Equipment.equipment_type == equipment_type)
            .limit(1),
        )
        if exists is None:
            raise KnowledgeEquipmentTypeNotFoundError

    applicability = KnowledgeDocumentApplicability(
        document_version_id=document_version_id,
        **payload.model_dump(),
    )
    db.add(applicability)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise KnowledgeConflictError(
            "Такая область применения уже задана для версии",
        ) from None
    db.refresh(applicability)
    return applicability


def remove_applicability(db: Session, applicability_id: int) -> None:
    """Удаляет ошибочно добавленную область применения."""
    applicability = db.get(KnowledgeDocumentApplicability, applicability_id)
    if applicability is None:
        raise KnowledgeApplicabilityNotFoundError
    db.delete(applicability)
    db.commit()


def list_documents(
    db: Session,
    *,
    document_type: DocumentType | None = None,
    language: str | None = None,
    equipment_id: int | None = None,
) -> list[KnowledgeDocument]:
    """Возвращает каталог, при необходимости только применимый к оборудованию."""
    statement = select(KnowledgeDocument)
    if document_type is not None:
        statement = statement.where(
            KnowledgeDocument.document_type == document_type,
        )
    if language is not None:
        statement = statement.where(KnowledgeDocument.language == language)
    if equipment_id is not None:
        equipment = db.get(Equipment, equipment_id)
        if equipment is None:
            raise KnowledgeEquipmentNotFoundError
        statement = (
            statement.join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
            )
            .join(
                KnowledgeDocumentApplicability,
                KnowledgeDocumentApplicability.document_version_id
                == KnowledgeDocumentVersion.id,
            )
            .where(
                KnowledgeDocumentVersion.is_current.is_(True),
                or_(
                    KnowledgeDocumentApplicability.equipment_id == equipment_id,
                    KnowledgeDocumentApplicability.equipment_type
                    == equipment.equipment_type,
                ),
            )
            .distinct()
        )
    return list(db.scalars(statement.order_by(KnowledgeDocument.id)))


def get_document_detail(
    db: Session,
    document_id: int,
) -> KnowledgeDocumentDetail:
    """Собирает карточку документа без загрузки бинарного содержимого."""
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise KnowledgeDocumentNotFoundError
    versions = list(
        db.scalars(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(
                KnowledgeDocumentVersion.created_at.desc(),
                KnowledgeDocumentVersion.id.desc(),
            ),
        ),
    )
    version_ids = [version.id for version in versions]
    applicability_by_version = {version_id: [] for version_id in version_ids}
    if version_ids:
        for item in db.scalars(
            select(KnowledgeDocumentApplicability)
            .where(
                KnowledgeDocumentApplicability.document_version_id.in_(
                    version_ids,
                ),
            )
            .order_by(KnowledgeDocumentApplicability.id),
        ):
            applicability_by_version[item.document_version_id].append(item)

    document_data = KnowledgeDocumentResponse.model_validate(document).model_dump()
    return KnowledgeDocumentDetail(
        **document_data,
        versions=[
            KnowledgeDocumentVersionDetail(
                **KnowledgeDocumentVersionResponse.model_validate(
                    version,
                ).model_dump(),
                applicability=[
                    KnowledgeApplicabilityResponse.model_validate(item)
                    for item in applicability_by_version[version.id]
                ],
            )
            for version in versions
        ],
    )


def get_document_version(
    db: Session,
    document_version_id: int,
) -> KnowledgeDocumentVersion:
    """Возвращает версию вместе с бинарным содержимым для скачивания."""
    version = db.get(KnowledgeDocumentVersion, document_version_id)
    if version is None:
        raise KnowledgeDocumentVersionNotFoundError
    return version
