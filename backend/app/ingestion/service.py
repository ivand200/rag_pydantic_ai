from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.documents.chunking import split_text_into_chunks
from app.documents.extraction import DocumentExtractionError, extract_document_text
from app.models.rag import Document, DocumentChunk, DocumentEmbedding, IngestionJob
from app.retrieval.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from app.storage.service import ObjectStorage

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"

DOCUMENT_STATUS_QUEUED = "queued"
DOCUMENT_STATUS_PROCESSING = "processing"
DOCUMENT_STATUS_COMPLETED = "completed"
DOCUMENT_STATUS_FAILED = "failed"

MAX_ERROR_CHARS = 500


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    document_id: UUID
    attempt_count: int


class IngestionWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: ObjectStorage,
        embedding_provider: EmbeddingProvider | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._embedding_provider = embedding_provider or OpenAIEmbeddingProvider(settings=settings)
        self._worker_id = worker_id or settings.ingestion_worker_id

    def process_next_job(self, *, db: Session) -> bool:
        claimed = self.claim_next_job(db=db)
        if claimed is None:
            return False

        try:
            self.process_claimed_job(db=db, job_id=claimed.id)
        except DocumentExtractionError as exc:
            self.mark_job_failed(
                db=db,
                job_id=claimed.id,
                error=exc.message,
                retryable=exc.retryable,
            )
        except Exception as exc:
            self.mark_job_failed(db=db, job_id=claimed.id, error=str(exc), retryable=True)
        return True

    def claim_next_job(self, *, db: Session) -> ClaimedJob | None:
        now = datetime.now(UTC)
        job = db.execute(
            select(IngestionJob)
            .where(
                IngestionJob.status == JOB_STATUS_QUEUED,
                IngestionJob.next_run_at <= now,
            )
            .order_by(IngestionJob.next_run_at.asc(), IngestionJob.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if job is None:
            db.rollback()
            return None

        job.status = JOB_STATUS_PROCESSING
        job.attempt_count += 1
        job.locked_at = now
        job.locked_by = self._worker_id
        job.updated_at = now

        document = db.get(Document, job.document_id)
        if document is not None and document.deleted_at is None:
            document.status = DOCUMENT_STATUS_PROCESSING
            document.updated_at = now

        db.commit()
        return ClaimedJob(id=job.id, document_id=job.document_id, attempt_count=job.attempt_count)

    def process_claimed_job(self, *, db: Session, job_id: UUID) -> None:
        job = db.get(IngestionJob, job_id)
        if job is None:
            return

        document = db.get(Document, job.document_id)
        if document is None:
            self._complete_job(db=db, job=job, now=datetime.now(UTC))
            db.commit()
            return

        if document.deleted_at is not None:
            self._complete_job(db=db, job=job, now=datetime.now(UTC))
            db.commit()
            return

        content = self._storage.get_original(key=document.object_key)
        extracted = extract_document_text(
            content=content,
            file_extension=document.file_extension,
            max_chars=self._settings.max_extracted_chars,
        )
        chunks = split_text_into_chunks(
            text=extracted.text,
            target_tokens=self._settings.rag_chunk_target_tokens,
            overlap_tokens=self._settings.rag_chunk_overlap_tokens,
        )
        if not chunks:
            raise DocumentExtractionError("Document has no chunkable text.")

        now = datetime.now(UTC)
        existing_chunk_ids = select(DocumentChunk.id).where(
            DocumentChunk.document_id == document.id
        )
        db.execute(
            delete(DocumentEmbedding).where(DocumentEmbedding.chunk_id.in_(existing_chunk_ids))
        )
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
        chunk_rows: list[DocumentChunk] = []
        for chunk in chunks:
            chunk_rows.append(
                DocumentChunk(
                    id=uuid4(),
                    document_id=document.id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    page_number=None,
                    section_title=chunk.section_title,
                    chunk_metadata={},
                    created_at=now,
                )
            )
        db.add_all(chunk_rows)

        embeddings = self._embedding_provider.embed_texts([chunk.text for chunk in chunk_rows])
        for chunk_row, embedding in zip(chunk_rows, embeddings, strict=True):
            db.add(
                DocumentEmbedding(
                    id=uuid4(),
                    chunk_id=chunk_row.id,
                    embedding_model=self._embedding_provider.model,
                    embedding=embedding,
                    created_at=now,
                )
            )

        document.status = DOCUMENT_STATUS_COMPLETED
        document.failure_reason = None
        document.updated_at = now
        self._complete_job(db=db, job=job, now=now)
        db.commit()

    def mark_job_failed(
        self,
        *,
        db: Session,
        job_id: UUID,
        error: str,
        retryable: bool,
    ) -> None:
        db.rollback()
        job = db.get(IngestionJob, job_id)
        if job is None:
            return

        document = db.get(Document, job.document_id)
        now = datetime.now(UTC)
        sanitized_error = _sanitize_error(error)
        should_retry = retryable and job.attempt_count < job.max_attempts
        if should_retry:
            job.status = JOB_STATUS_QUEUED
            job.next_run_at = now + _retry_delay(
                base_seconds=self._settings.ingestion_base_retry_seconds,
                attempt_count=job.attempt_count,
            )
            if document is not None and document.deleted_at is None:
                document.status = DOCUMENT_STATUS_QUEUED
                document.updated_at = now
        else:
            job.status = JOB_STATUS_FAILED
            job.completed_at = now
            if document is not None and document.deleted_at is None:
                document.status = DOCUMENT_STATUS_FAILED
                document.failure_reason = sanitized_error
                document.updated_at = now

        job.locked_at = None
        job.locked_by = None
        job.last_error = sanitized_error
        job.updated_at = now
        db.commit()

    def _complete_job(self, *, db: Session, job: IngestionJob, now: datetime) -> None:
        job.status = JOB_STATUS_COMPLETED
        job.locked_at = None
        job.locked_by = None
        job.completed_at = now
        job.updated_at = now


def _retry_delay(*, base_seconds: int, attempt_count: int) -> timedelta:
    return timedelta(seconds=base_seconds * (2 ** max(attempt_count - 1, 0)))


def _sanitize_error(error: str) -> str:
    single_line = " ".join(error.split())
    if not single_line:
        return "Ingestion failed."
    return single_line[:MAX_ERROR_CHARS]
