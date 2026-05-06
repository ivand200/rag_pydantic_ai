from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

import app.ingestion.worker as worker_module


@pytest.fixture(autouse=True)
def enable_worker_logger() -> None:
    logging.getLogger(worker_module.__name__).disabled = False


def test_worker_runs_recovery_on_startup_and_before_claim() -> None:
    fake_worker = FakeWorker(processed=[False])
    session_factory = FakeSessionFactory()

    worker_module.run_worker_loop(
        worker=fake_worker,
        session_factory=session_factory,
        once=True,
        poll_seconds=0,
    )

    assert fake_worker.events == [
        ("recover", "db-1"),
        ("recover", "db-2"),
        ("process", "db-2"),
    ]


def test_idle_shutdown_exits_after_poll_without_more_claims() -> None:
    shutdown = PollShutdown()
    fake_worker = FakeWorker(processed=[False, False])

    worker_module.run_worker_loop(
        worker=fake_worker,
        session_factory=FakeSessionFactory(),
        once=False,
        poll_seconds=30,
        shutdown=shutdown,
    )

    process_events = [event for event in fake_worker.events if event[0] == "process"]
    assert process_events == [("process", "db-2")]


def test_shutdown_during_job_finishes_current_job_without_second_claim() -> None:
    shutdown = worker_module.ShutdownController()
    fake_worker = FakeWorker(processed=[True, True], shutdown=shutdown)

    worker_module.run_worker_loop(
        worker=fake_worker,
        session_factory=FakeSessionFactory(),
        once=False,
        poll_seconds=0,
        shutdown=shutdown,
    )

    process_events = [event for event in fake_worker.events if event[0] == "process"]
    assert process_events == [("process", "db-2")]


def test_once_preserves_single_claim_when_work_is_available() -> None:
    fake_worker = FakeWorker(processed=[True, True])

    worker_module.run_worker_loop(
        worker=fake_worker,
        session_factory=FakeSessionFactory(),
        once=True,
        poll_seconds=0,
    )

    process_events = [event for event in fake_worker.events if event[0] == "process"]
    assert process_events == [("process", "db-2")]


def test_queue_health_cli_prints_json_shape_and_logs_event(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_worker = FakeWorker(
        queue_health={
            "queued_count": 2,
            "processing_count": 1,
            "failed_count": 3,
            "oldest_queued_age_seconds": 42,
        }
    )
    monkeypatch.setattr(worker_module, "get_settings", lambda: object())
    monkeypatch.setattr(worker_module, "get_object_storage", lambda: object())
    monkeypatch.setattr(worker_module, "get_sessionmaker", lambda: FakeSessionFactory())
    monkeypatch.setattr(worker_module, "IngestionWorker", lambda **_: fake_worker)

    with caplog.at_level(logging.INFO, logger=worker_module.__name__):
        worker_module.main(["--queue-health"])

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "failed_count": 3,
        "oldest_queued_age_seconds": 42,
        "processing_count": 1,
        "queued_count": 2,
    }
    assert _log_events(caplog) == ["ingestion.queue_health"]


class FakeSessionFactory:
    def __init__(self) -> None:
        self._counter = 0

    def __call__(self) -> Iterator[str]:
        self._counter += 1
        return FakeSession(f"db-{self._counter}")


class FakeSession:
    def __init__(self, label: str) -> None:
        self.label = label

    def __enter__(self) -> str:
        return self.label

    def __exit__(self, *_exc: object) -> None:
        return None


class FakeWorker:
    def __init__(
        self,
        *,
        processed: list[bool] | None = None,
        shutdown: worker_module.ShutdownController | None = None,
        queue_health: dict[str, int | None] | None = None,
    ) -> None:
        self._processed = processed or []
        self._shutdown = shutdown
        self._queue_health = queue_health or {
            "queued_count": 0,
            "processing_count": 0,
            "failed_count": 0,
            "oldest_queued_age_seconds": None,
        }
        self.events: list[tuple[str, str]] = []

    def recover_stale_jobs(self, *, db: str) -> None:
        self.events.append(("recover", db))

    def process_next_job(self, *, db: str) -> bool:
        self.events.append(("process", db))
        if self._shutdown is not None:
            self._shutdown.request()
        if not self._processed:
            return False
        return self._processed.pop(0)

    def get_queue_health(self, *, db: Any) -> dict[str, int | None]:
        return self._queue_health


class PollShutdown:
    def __init__(self) -> None:
        self._requested = False

    @property
    def requested(self) -> bool:
        return self._requested

    def wait(self, timeout: float) -> bool:
        self._requested = True
        return True


def _log_events(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.event for record in caplog.records if hasattr(record, "event")]
