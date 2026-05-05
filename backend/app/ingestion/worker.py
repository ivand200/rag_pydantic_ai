from __future__ import annotations

import argparse
import time

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.ingestion.service import IngestionWorker
from app.storage.dependencies import get_object_storage


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the document ingestion worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one available job.")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()

    settings = get_settings()
    worker = IngestionWorker(settings=settings, storage=get_object_storage())
    session_factory = get_sessionmaker()

    while True:
        with session_factory() as db:
            processed = worker.process_next_job(db=db)

        if args.once:
            return
        if not processed:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
