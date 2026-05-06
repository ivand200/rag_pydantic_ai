from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.ingestion.service import IngestionWorker
from app.models.rag import IngestionJob
from app.storage.dependencies import get_object_storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueueHealth:
    queued_count: int
    processing_count: int
    failed_count: int
    oldest_queued_age_seconds: int | None


class ShutdownController:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def request(self, signum: int | None = None, _frame: object | None = None) -> None:
        self._event.set()
        logger.info(
            "Ingestion worker shutdown requested.",
            extra={"event": "ingestion.shutdown_requested", "signal": signum},
        )

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


def run_worker_loop(
    *,
    worker: IngestionWorker,
    session_factory: Any,
    once: bool,
    poll_seconds: float,
    shutdown: ShutdownController | None = None,
) -> None:
    shutdown = shutdown or ShutdownController()

    with session_factory() as db:
        _recover_stale_jobs(worker=worker, db=db)

    while not shutdown.requested:
        with session_factory() as db:
            _recover_stale_jobs(worker=worker, db=db)
            if shutdown.requested:
                break
            processed = worker.process_next_job(db=db)

        if once or shutdown.requested:
            break
        if not processed:
            shutdown.wait(poll_seconds)

    logger.info(
        "Ingestion worker shutdown completed.",
        extra={"event": "ingestion.shutdown_completed"},
    )


def print_queue_health(*, worker: IngestionWorker, session_factory: Any) -> None:
    with session_factory() as db:
        health = _queue_health(worker=worker, db=db)

    payload = asdict(health)
    logger.info("Ingestion queue health.", extra={"event": "ingestion.queue_health", **payload})
    print(json.dumps(payload, sort_keys=True))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the document ingestion worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one available job.")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument(
        "--queue-health",
        action="store_true",
        help="Print internal ingestion queue health as JSON and exit.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    worker = IngestionWorker(settings=settings, storage=get_object_storage())
    session_factory = get_sessionmaker()

    if args.queue_health:
        print_queue_health(worker=worker, session_factory=session_factory)
        return

    shutdown = ShutdownController()
    _install_signal_handlers(shutdown)
    run_worker_loop(
        worker=worker,
        session_factory=session_factory,
        once=args.once,
        poll_seconds=args.poll_seconds,
        shutdown=shutdown,
    )


def _install_signal_handlers(shutdown: ShutdownController) -> None:
    signal.signal(signal.SIGINT, shutdown.request)
    signal.signal(signal.SIGTERM, shutdown.request)


def _recover_stale_jobs(*, worker: IngestionWorker, db: Any) -> None:
    recover = getattr(worker, "recover_stale_jobs", None)
    if recover is None:
        return
    recover(db=db)


def _queue_health(*, worker: IngestionWorker, db: Any) -> QueueHealth:
    for method_name in ("get_queue_health", "queue_health_summary"):
        method = getattr(worker, method_name, None)
        if method is None:
            continue
        return _coerce_queue_health(method(db=db))
    return _query_queue_health(db=db)


def _coerce_queue_health(summary: Any) -> QueueHealth:
    if isinstance(summary, QueueHealth):
        return summary
    if isinstance(summary, dict):
        return QueueHealth(
            queued_count=int(summary["queued_count"]),
            processing_count=int(summary["processing_count"]),
            failed_count=int(summary["failed_count"]),
            oldest_queued_age_seconds=summary["oldest_queued_age_seconds"],
        )
    return QueueHealth(
        queued_count=int(summary.queued_count),
        processing_count=int(summary.processing_count),
        failed_count=int(summary.failed_count),
        oldest_queued_age_seconds=summary.oldest_queued_age_seconds,
    )


def _query_queue_health(*, db: Any) -> QueueHealth:
    now = datetime.now(UTC)
    counts = dict(
        db.execute(
            select(IngestionJob.status, func.count(IngestionJob.id))
            .where(IngestionJob.status.in_(("queued", "processing", "failed")))
            .group_by(IngestionJob.status)
        ).all()
    )
    oldest_queued_at = db.execute(
        select(func.min(IngestionJob.created_at)).where(IngestionJob.status == "queued")
    ).scalar_one_or_none()
    oldest_age = None
    if oldest_queued_at is not None:
        oldest_age = max(0, int((now - oldest_queued_at).total_seconds()))
    return QueueHealth(
        queued_count=int(counts.get("queued", 0)),
        processing_count=int(counts.get("processing", 0)),
        failed_count=int(counts.get("failed", 0)),
        oldest_queued_age_seconds=oldest_age,
    )


if __name__ == "__main__":
    main()
