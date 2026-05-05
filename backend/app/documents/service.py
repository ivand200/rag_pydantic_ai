from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.documents.schemas import DocumentResponse, DocumentUser
from app.models.app_user import AppUser
from app.models.rag import Document, IngestionJob
from app.storage.service import ObjectStorage

ALLOWED_DOCUMENT_TYPES = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}
DOCUMENT_STATUS_QUEUED = "queued"
INGESTION_JOB_STATUS_QUEUED = "queued"


class DocumentUploadError(Exception):
    code = "invalid_upload"
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MissingDocumentFileError(DocumentUploadError):
    code = "missing_file"


class MultipleDocumentFilesError(DocumentUploadError):
    code = "multiple_files"


class UnsupportedDocumentTypeError(DocumentUploadError):
    code = "unsupported_file_type"
    status_code = 415


class UploadTooLargeError(DocumentUploadError):
    code = "upload_too_large"
    status_code = 413


@dataclass(frozen=True)
class DocumentUpload:
    filename: str
    content: bytes


def create_document(
    *,
    db: Session,
    storage: ObjectStorage,
    settings: Settings,
    app_user: AppUser,
    upload: DocumentUpload,
) -> DocumentResponse:
    extension = _validate_extension(upload.filename)
    if len(upload.content) > settings.max_upload_bytes:
        raise UploadTooLargeError("Document exceeds the configured upload size limit.")

    media_type = ALLOWED_DOCUMENT_TYPES[extension]
    object_key = _generate_object_key(extension)
    stored_object = storage.put_original(
        key=object_key,
        content=upload.content,
        content_type=media_type,
    )
    now = datetime.now(UTC)
    document = Document(
        id=uuid4(),
        original_filename=upload.filename,
        display_name=_display_name(upload.filename),
        media_type=media_type,
        file_extension=extension,
        byte_size=stored_object.byte_size,
        sha256=stored_object.sha256,
        object_bucket=stored_object.bucket,
        object_key=stored_object.key,
        status=DOCUMENT_STATUS_QUEUED,
        uploaded_by_app_user_id=app_user.id,
        created_at=now,
        updated_at=now,
    )
    job = IngestionJob(
        id=uuid4(),
        document_id=document.id,
        status=INGESTION_JOB_STATUS_QUEUED,
        attempt_count=0,
        max_attempts=settings.ingestion_max_attempts,
        next_run_at=now,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(document)
        db.add(job)
        db.flush()
        db.commit()
    except Exception:
        storage.delete_original(key=object_key)
        raise

    return _to_response(document, app_user)


def list_active_documents(*, db: Session) -> list[DocumentResponse]:
    rows = db.execute(
        select(Document, AppUser)
        .join(AppUser, Document.uploaded_by_app_user_id == AppUser.id)
        .where(Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    ).all()
    return [_to_response(document, uploaded_by) for document, uploaded_by in rows]


def delete_document(
    *,
    db: Session,
    document_id: UUID,
    deleted_by: AppUser,
) -> DocumentResponse | None:
    row = db.execute(
        select(Document, AppUser)
        .join(AppUser, Document.uploaded_by_app_user_id == AppUser.id)
        .where(Document.id == document_id)
    ).one_or_none()
    if row is None:
        return None

    document, uploaded_by = row
    if document.deleted_at is None:
        now = datetime.now(UTC)
        document.deleted_at = now
        document.deleted_by_app_user_id = deleted_by.id
        document.updated_at = now
        db.flush()

    return _to_response(document, uploaded_by)


def _validate_extension(filename: str) -> str:
    extension = PurePath(filename).suffix.lower()
    if extension not in ALLOWED_DOCUMENT_TYPES:
        raise UnsupportedDocumentTypeError("Only .txt, .md, and .pdf documents are supported.")
    return extension


def _display_name(filename: str) -> str:
    candidate = PurePath(filename).name.strip()
    if not candidate:
        return "document"
    return "".join(char for char in candidate if char.isprintable())


def _generate_object_key(extension: str) -> str:
    return f"documents/originals/{uuid4().hex}{extension}"


def _to_response(document: Document, uploaded_by: AppUser) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.display_name,
        media_type=document.media_type,
        byte_size=document.byte_size,
        status=document.status,
        uploaded_by=DocumentUser(
            id=uploaded_by.id,
            email=uploaded_by.email,
            first_name=uploaded_by.first_name,
            last_name=uploaded_by.last_name,
        ),
        uploaded_at=document.created_at,
        deleted=document.deleted_at is not None,
        deleted_at=document.deleted_at,
        failure_reason=document.failure_reason,
    )
