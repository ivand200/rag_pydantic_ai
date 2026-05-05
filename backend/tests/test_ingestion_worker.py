from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.ingestion.service as ingestion_service
from app.core.config import Settings
from app.documents.chunking import TextChunk
from app.ingestion.service import IngestionWorker
from app.models.app_user import AppUser
from app.models.rag import Document, DocumentChunk, DocumentEmbedding, IngestionJob
from app.storage.fake import FakeObjectStorage


@pytest.fixture
def db_session(migrated_database: Engine) -> Iterator[Session]:
    session_factory = sessionmaker(bind=migrated_database, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


def test_worker_claims_due_job_and_marks_document_processing(db_session: Session) -> None:
    storage = FakeObjectStorage()
    document, job = create_queued_document(db_session, storage, content=b"hello", extension=".txt")
    worker = IngestionWorker(
        settings=make_settings(),
        storage=storage,
        embedding_provider=FakeEmbeddingProvider(),
        worker_id="worker-a",
    )

    claimed = worker.claim_next_job(db=db_session)

    db_session.refresh(document)
    db_session.refresh(job)
    assert claimed is not None
    assert job.status == "processing"
    assert document.status == "processing"
    assert job.locked_by == "worker-a"


def test_worker_processes_text_document_into_chunks_and_completes_job(
    db_session: Session,
) -> None:
    storage = FakeObjectStorage()
    document, job = create_queued_document(
        db_session,
        storage,
        content=b"Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu.",
        extension=".txt",
    )
    worker = IngestionWorker(
        settings=make_settings(),
        storage=storage,
        embedding_provider=FakeEmbeddingProvider(),
    )

    processed = worker.process_next_job(db=db_session)

    db_session.refresh(document)
    db_session.refresh(job)
    chunks = db_session.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    assert processed is True
    assert (document.status, job.status) == ("completed", "completed")
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert len(chunks) > 1
    assert db_session.query(DocumentEmbedding).join(DocumentChunk).filter(
        DocumentChunk.document_id == document.id
    ).count() == len(chunks)


def test_worker_retries_transient_storage_failure_then_marks_final_failure(
    db_session: Session,
) -> None:
    storage = FakeObjectStorage()
    document, job = create_queued_document(
        db_session,
        storage,
        content=b"hello",
        extension=".txt",
        max_attempts=2,
    )
    storage.objects.clear()
    worker = IngestionWorker(
        settings=make_settings(),
        storage=storage,
        embedding_provider=FakeEmbeddingProvider(),
    )

    first_processed = worker.process_next_job(db=db_session)
    job.next_run_at = datetime.now(UTC)
    db_session.commit()
    second_processed = worker.process_next_job(db=db_session)

    db_session.refresh(document)
    db_session.refresh(job)
    assert (first_processed, second_processed) == (True, True)
    assert (job.attempt_count, job.status, document.status) == (2, "failed", "failed")
    assert job.last_error is not None


def test_worker_retries_failed_chunk_write_without_losing_completed_chunks(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = FakeObjectStorage()
    document, job = create_queued_document(
        db_session,
        storage,
        content=b"new text",
        extension=".txt",
    )
    original_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=0,
        text="previous completed chunk",
        token_count=3,
        page_number=None,
        section_title=None,
        chunk_metadata={},
        created_at=datetime.now(UTC),
    )
    db_session.add(original_chunk)
    db_session.commit()
    monkeypatch.setattr(
        ingestion_service,
        "split_text_into_chunks",
        lambda **_: [
            TextChunk(chunk_index=0, text="first replacement", token_count=2),
            TextChunk(chunk_index=0, text="duplicate replacement", token_count=2),
        ],
    )
    worker = IngestionWorker(
        settings=make_settings(),
        storage=storage,
        embedding_provider=FakeEmbeddingProvider(),
    )

    processed = worker.process_next_job(db=db_session)

    db_session.refresh(document)
    db_session.refresh(job)
    chunk_texts = db_session.scalars(
        select(DocumentChunk.text).where(DocumentChunk.document_id == document.id)
    ).all()
    assert (processed, job.status, document.status) == (True, "queued", "queued")
    assert chunk_texts == ["previous completed chunk"]


def test_worker_retries_embedding_failure_without_persisting_partial_chunks(
    db_session: Session,
) -> None:
    storage = FakeObjectStorage()
    document, job = create_queued_document(
        db_session,
        storage,
        content=b"Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu.",
        extension=".txt",
    )
    worker = IngestionWorker(
        settings=make_settings(),
        storage=storage,
        embedding_provider=FailingEmbeddingProvider(),
    )

    processed = worker.process_next_job(db=db_session)

    db_session.refresh(document)
    db_session.refresh(job)
    chunk_count = db_session.query(DocumentChunk).filter_by(document_id=document.id).count()
    embedding_count = (
        db_session.query(DocumentEmbedding)
        .join(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .count()
    )
    assert (processed, job.attempt_count, job.status, document.status) == (
        True,
        1,
        "queued",
        "queued",
    )
    assert (chunk_count, embedding_count) == (0, 0)


def test_worker_marks_empty_pdf_as_clear_permanent_failure(db_session: Session) -> None:
    storage = FakeObjectStorage()
    document, job = create_queued_document(
        db_session,
        storage,
        content=blank_pdf_bytes(),
        extension=".pdf",
        media_type="application/pdf",
    )
    worker = IngestionWorker(
        settings=make_settings(),
        storage=storage,
        embedding_provider=FakeEmbeddingProvider(),
    )

    worker.process_next_job(db=db_session)

    db_session.refresh(document)
    db_session.refresh(job)
    assert (job.attempt_count, job.status, document.status) == (1, "failed", "failed")
    assert document.failure_reason is not None
    assert "no extractable text layer" in document.failure_reason


def test_worker_skips_tombstoned_document_without_creating_chunks(db_session: Session) -> None:
    storage = FakeObjectStorage()
    document, job = create_queued_document(db_session, storage, content=b"hello", extension=".txt")
    document.deleted_at = datetime.now(UTC)
    db_session.commit()
    worker = IngestionWorker(
        settings=make_settings(),
        storage=storage,
        embedding_provider=FakeEmbeddingProvider(),
    )

    processed = worker.process_next_job(db=db_session)

    db_session.refresh(job)
    chunk_count = db_session.query(DocumentChunk).filter_by(document_id=document.id).count()
    assert processed is True
    assert job.status == "completed"
    assert chunk_count == 0


def create_queued_document(
    db: Session,
    storage: FakeObjectStorage,
    *,
    content: bytes,
    extension: str,
    media_type: str = "text/plain",
    max_attempts: int = 3,
) -> tuple[Document, IngestionJob]:
    now = datetime.now(UTC)
    app_user = AppUser(
        id=uuid4(),
        clerk_user_id=f"user_{uuid4().hex}",
        email="reader@example.com",
        first_name=None,
        last_name=None,
        created_at=now,
        updated_at=now,
    )
    object_key = f"documents/originals/{uuid4().hex}{extension}"
    storage.put_original(key=object_key, content=content, content_type=media_type)
    document = Document(
        id=uuid4(),
        original_filename=f"document{extension}",
        display_name=f"document{extension}",
        media_type=media_type,
        file_extension=extension,
        byte_size=len(content),
        sha256=sha256(content).hexdigest(),
        object_bucket=storage.bucket,
        object_key=object_key,
        status="queued",
        uploaded_by_app_user_id=app_user.id,
        created_at=now,
        updated_at=now,
    )
    job = IngestionJob(
        id=uuid4(),
        document_id=document.id,
        status="queued",
        attempt_count=0,
        max_attempts=max_attempts,
        next_run_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add_all([app_user, document, job])
    db.commit()
    return document, job


def make_settings() -> Settings:
    return Settings(
        rag_chunk_target_tokens=5,
        rag_chunk_overlap_tokens=2,
        max_extracted_chars=1_000,
        ingestion_base_retry_seconds=1,
    )


class FakeEmbeddingProvider:
    model = "test-embedding"

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [_embedding_for_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return _embedding_for_text(text)


class FailingEmbeddingProvider:
    model = "test-embedding"

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("embedding service unavailable")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embedding service unavailable")


def _embedding_for_text(text: str) -> list[float]:
    embedding = [0.0] * 1536
    embedding[0] = 1.0
    embedding[1] = float(len(text) % 7) / 10
    return embedding


def blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
