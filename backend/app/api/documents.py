from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import Settings, get_settings
from app.dependencies import get_current_app_user, get_db_session
from app.documents.schemas import DocumentResponse
from app.documents.service import (
    DocumentUpload,
    DocumentUploadError,
    MissingDocumentFileError,
    MultipleDocumentFilesError,
    UploadTooLargeError,
    create_document,
    delete_document,
    list_active_documents,
)
from app.models.app_user import AppUser
from app.storage.dependencies import get_object_storage
from app.storage.service import ObjectStorage

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    app_user: Annotated[AppUser, Depends(get_current_app_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> list[DocumentResponse]:
    _ = app_user
    return list_active_documents(db=db)


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    request: Request,
    app_user: Annotated[AppUser, Depends(get_current_app_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    db: Annotated[Session, Depends(get_db_session)],
) -> DocumentResponse:
    try:
        upload = await _read_one_upload(request, settings.max_upload_bytes)
        return create_document(
            db=db,
            storage=storage,
            settings=settings,
            app_user=app_user,
            upload=upload,
        )
    except DocumentUploadError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.delete("/{document_id}", response_model=DocumentResponse)
def tombstone_document(
    document_id: UUID,
    app_user: Annotated[AppUser, Depends(get_current_app_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> DocumentResponse:
    document = delete_document(db=db, document_id=document_id, deleted_by=app_user)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "document_not_found"})
    return document


async def _read_one_upload(request: Request, max_upload_bytes: int) -> DocumentUpload:
    form = await request.form()
    files = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
    if not files:
        raise MissingDocumentFileError("Upload request must include one document file.")
    if len(files) > 1:
        raise MultipleDocumentFilesError("Upload request must include exactly one document file.")

    file = files[0]
    content = await _read_with_size_limit(file, max_upload_bytes)
    return DocumentUpload(filename=file.filename or "", content=content)


async def _read_with_size_limit(file: UploadFile, max_upload_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total_size = 0
    while chunk := await file.read(1024 * 1024):
        total_size += len(chunk)
        if total_size > max_upload_bytes:
            raise UploadTooLargeError("Document exceeds the configured upload size limit.")
        chunks.append(chunk)
    return b"".join(chunks)
