"""API приёма и каталогизации технической документации."""

from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.database import get_db
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
    KnowledgeDocumentVersionResponse,
)
from app.knowledge.service import (
    MAX_DOCUMENT_SIZE_BYTES,
    InvalidKnowledgeFileError,
    KnowledgeApplicabilityNotFoundError,
    KnowledgeConflictError,
    KnowledgeDocumentNotFoundError,
    KnowledgeDocumentVersionNotFoundError,
    KnowledgeEquipmentNotFoundError,
    KnowledgeEquipmentTypeNotFoundError,
    add_applicability,
    add_document_version,
    create_document,
    get_document_detail,
    get_document_version,
    list_documents,
    remove_applicability,
)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document_endpoint(
    payload: KnowledgeDocumentCreate,
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    """Создаёт карточку технического документа."""
    return create_document(db, payload)


@router.get(
    "/documents",
    response_model=list[KnowledgeDocumentResponse],
)
def list_documents_endpoint(
    document_type: DocumentType | None = None,
    language: Annotated[str | None, Query(min_length=2, max_length=10)] = None,
    equipment_id: Annotated[int | None, Query(gt=0)] = None,
    db: Session = Depends(get_db),
) -> list[KnowledgeDocument]:
    """Возвращает каталог с фильтрами и проверкой применимости."""
    try:
        return list_documents(
            db,
            document_type=document_type,
            language=language,
            equipment_id=equipment_id,
        )
    except KnowledgeEquipmentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        ) from None


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentDetail,
)
def get_document_endpoint(
    document_id: int,
    db: Session = Depends(get_db),
) -> KnowledgeDocumentDetail:
    """Возвращает версии и области применения документа."""
    try:
        return get_document_detail(db, document_id)
    except KnowledgeDocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден",
        ) from None


@router.post(
    "/documents/{document_id}/versions",
    response_model=KnowledgeDocumentVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document_version_endpoint(
    document_id: int,
    version: Annotated[str, Form(min_length=1, max_length=50)],
    file: Annotated[UploadFile, File()],
    source_uri: Annotated[str | None, Form(max_length=500)] = None,
    db: Session = Depends(get_db),
) -> KnowledgeDocumentVersion:
    """Принимает PDF/TXT/Markdown размером не более 10 МБ."""
    content = file.file.read(MAX_DOCUMENT_SIZE_BYTES + 1)
    try:
        return add_document_version(
            db,
            document_id,
            version=version,
            filename=file.filename or "",
            mime_type=file.content_type,
            content=content,
            source_uri=source_uri,
        )
    except KnowledgeDocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден",
        ) from None
    except InvalidKnowledgeFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except KnowledgeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/versions/{document_version_id}/applicability",
    response_model=KnowledgeApplicabilityResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_applicability_endpoint(
    document_version_id: int,
    payload: KnowledgeApplicabilityCreate,
    db: Session = Depends(get_db),
) -> KnowledgeDocumentApplicability:
    """Задаёт применимость версии к типу или единице оборудования."""
    try:
        return add_applicability(db, document_version_id, payload)
    except KnowledgeDocumentVersionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Версия документа не найдена",
        ) from None
    except KnowledgeEquipmentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оборудование не найдено",
        ) from None
    except KnowledgeEquipmentTypeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Тип оборудования не найден",
        ) from None
    except KnowledgeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/applicability/{applicability_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_applicability_endpoint(
    applicability_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Удаляет ошибочную привязку документа."""
    try:
        remove_applicability(db, applicability_id)
    except KnowledgeApplicabilityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Область применения не найдена",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/versions/{document_version_id}/download")
def download_document_version_endpoint(
    document_version_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Возвращает исходный файл без преобразований."""
    try:
        version = get_document_version(db, document_version_id)
    except KnowledgeDocumentVersionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Версия документа не найдена",
        ) from None
    encoded_filename = quote(version.original_filename, safe="")
    return Response(
        content=version.content,
        media_type=version.mime_type,
        headers={
            "Content-Disposition": (f"attachment; filename*=UTF-8''{encoded_filename}"),
            "X-Content-SHA256": version.checksum_sha256,
        },
    )
