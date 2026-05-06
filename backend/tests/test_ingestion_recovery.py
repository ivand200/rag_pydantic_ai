from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.ingestion.service import IngestionWorker
from app.models.app_user import AppUser
from app.models.rag import Document, DocumentChunk, DocumentEmbedding, IngestionJob
from app.storage.fake import FakeObjectStorage


@pytest.fixture
def db_session(migrated_database: Engine) -> Iterator[Session]:
    logging.getLogger("app.ingestion.service").disabled = False
    session_factory = sessionmaker(bind=migrated_database, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def enable_service_logger() -> None:
    logging.getLogger("app.ingestion.service").disabled = False


def test_queue_health_summary_reports_counts_and_oldest_queued_age(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = FakeObjectStorage()
    now = datetime.now(UTC)
    create_ingestion_job(
        db_session,
        storage,
        status="queued",
        created_at=now - timedelta(seconds=45),
    )
    create_ingestion_job(db_session, storage, status="processing", locked_at=now)
    create_ingestion_job(db_session, storage, status="failed")
    worker = make_worker(storage)

    with caplog.at_level(logging.INFO, logger="app.ingestion.service"):
        summary = worker.queue_health_summary(db=db_session, now=now)

    assert (
        summary.queued_count,
        summary.processing_count,
        summary.failed_count,
        summary.oldest_queued_age_seconds,
    ) == (1, 1, 1, 45)
    health_log = event_record(caplog, "ingestion.queue_health")
    assert health_log.queued_count == 1
    assert health_log.oldest_queued_age_seconds == 45


def test_recovery_requeues_stale_job_without_consuming_attempt(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = FakeObjectStorage()
    now = datetime.now(UTC)
    document, job = create_ingestion_job(
        db_session,
        storage,
        status="processing",
        document_status="processing",
        attempt_count=1,
        max_attempts=3,
        locked_at=now - timedelta(seconds=61),
        locked_by="worker-that-stopped",
    )
    worker = make_worker(storage, worker_id="worker-b")

    with caplog.at_level(logging.INFO, logger="app.ingestion.service"):
        summary = worker.recover_stale_jobs(db=db_session, now=now)

    db_session.refresh(document)
    db_session.refresh(job)
    assert (summary.recovered_count, job.status, job.attempt_count, document.status) == (
        1,
        "queued",
        1,
        "queued",
    )
    assert (job.locked_at, job.locked_by, job.next_run_at) == (None, None, now)
    recovered_log = event_record(caplog, "ingestion.stale_recovered")
    assert (recovered_log.job_id, recovered_log.document_id, recovered_log.worker_id) == (
        str(job.id),
        str(document.id),
        "worker-b",
    )
    assert (recovered_log.attempt_count, recovered_log.max_attempts) == (1, 3)


def test_recovery_fails_exhausted_stale_job_with_exact_reason(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = FakeObjectStorage()
    now = datetime.now(UTC)
    document, job = create_ingestion_job(
        db_session,
        storage,
        status="processing",
        document_status="processing",
        attempt_count=2,
        max_attempts=2,
        locked_at=now - timedelta(seconds=61),
        locked_by="worker-that-stopped",
    )
    worker = make_worker(storage)

    with caplog.at_level(logging.INFO, logger="app.ingestion.service"):
        summary = worker.recover_stale_jobs(db=db_session, now=now)

    db_session.refresh(document)
    db_session.refresh(job)
    assert (summary.failed_count, job.status, document.status) == (1, "failed", "failed")
    assert job.last_error == "Stale ingestion job exceeded max attempts."
    assert document.failure_reason == "Stale ingestion job exceeded max attempts."
    assert (job.locked_at, job.locked_by) == (None, None)
    assert event_names(caplog) == ["ingestion.stale_failed"]


def test_recovery_respects_batch_limit(db_session: Session) -> None:
    storage = FakeObjectStorage()
    now = datetime.now(UTC)
    for index in range(3):
        create_ingestion_job(
            db_session,
            storage,
            status="processing",
            attempt_count=1,
            max_attempts=3,
            locked_at=now - timedelta(minutes=5, seconds=index),
            locked_by="worker-that-stopped",
        )
    worker = make_worker(storage)

    summary = worker.recover_stale_jobs(db=db_session, now=now, batch_size=2)

    processing_count = db_session.scalar(
        select(func.count(IngestionJob.id)).where(IngestionJob.status == "processing")
    )
    assert summary.recovered_count == 2
    assert processing_count == 1


def test_recovery_completes_tombstoned_stale_job_without_touching_document_or_chunks(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = FakeObjectStorage()
    now = datetime.now(UTC)
    document, job = create_ingestion_job(
        db_session,
        storage,
        status="processing",
        document_status="processing",
        document_failure_reason="keep this reason",
        deleted_at=now - timedelta(seconds=1),
        attempt_count=1,
        max_attempts=3,
        locked_at=now - timedelta(seconds=61),
        locked_by="worker-that-stopped",
    )
    worker = make_worker(storage)

    with caplog.at_level(logging.INFO, logger="app.ingestion.service"):
        summary = worker.recover_stale_jobs(db=db_session, now=now)

    db_session.refresh(document)
    db_session.refresh(job)
    chunk_count = db_session.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document.id)
    )
    embedding_count = db_session.scalar(select(func.count(DocumentEmbedding.id)))
    assert (summary.tombstoned_count, job.status, document.status, document.failure_reason) == (
        1,
        "completed",
        "processing",
        "keep this reason",
    )
    assert (job.locked_at, job.locked_by, chunk_count, embedding_count) == (None, None, 0, 0)
    assert event_names(caplog) == ["ingestion.tombstone_skipped"]


def create_ingestion_job(
    db: Session,
    storage: FakeObjectStorage,
    *,
    status: str,
    document_status: str | None = None,
    document_failure_reason: str | None = None,
    content: bytes = b"hello",
    extension: str = ".txt",
    media_type: str = "text/plain",
    attempt_count: int = 0,
    max_attempts: int = 3,
    created_at: datetime | None = None,
    next_run_at: datetime | None = None,
    locked_at: datetime | None = None,
    locked_by: str | None = None,
    deleted_at: datetime | None = None,
) -> tuple[Document, IngestionJob]:
    now = datetime.now(UTC)
    created_at = created_at or now
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
        status=document_status or status,
        failure_reason=document_failure_reason,
        uploaded_by_app_user_id=app_user.id,
        created_at=created_at,
        updated_at=created_at,
        deleted_at=deleted_at,
    )
    job = IngestionJob(
        id=uuid4(),
        document_id=document.id,
        status=status,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        next_run_at=next_run_at or created_at,
        locked_at=locked_at,
        locked_by=locked_by,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add_all([app_user, document, job])
    db.commit()
    return document, job


def make_worker(storage: FakeObjectStorage, *, worker_id: str = "worker-a") -> IngestionWorker:
    return IngestionWorker(
        settings=Settings(
            ingestion_stale_after_seconds=60,
            ingestion_stale_recovery_batch_size=10,
            _env_file=None,
        ),
        storage=storage,
        embedding_provider=FakeEmbeddingProvider(),
        worker_id=worker_id,
    )


def event_names(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.event for record in caplog.records if hasattr(record, "event")]


def event_record(caplog: pytest.LogCaptureFixture, event: str) -> logging.LogRecord:
    for record in caplog.records:
        if getattr(record, "event", None) == event:
            return record
    raise AssertionError(f"Missing log event: {event}")


class FakeEmbeddingProvider:
    model = "test-embedding"

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 1536
