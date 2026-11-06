"""Отдельный процесс durable worker-а экспериментов."""

import os
import signal
import socket
from threading import Event
from uuid import uuid4

import structlog

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.experiments.queue import process_next_run, recover_expired_runs

logger = structlog.get_logger(__name__)


def make_worker_id() -> str:
    """Формирует диагностический, но уникальный ID процесса."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"


def run_worker(stop_event: Event, *, worker_id: str | None = None) -> None:
    """Обрабатывает очередь до получения сигнала остановки."""
    resolved_worker_id = worker_id or make_worker_id()
    logger.info("experiment_worker_started", worker_id=resolved_worker_id)

    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                recover_expired_runs(db)
            processed = process_next_run(SessionLocal, resolved_worker_id)
        except Exception:
            logger.exception(
                "experiment_worker_iteration_failed",
                worker_id=resolved_worker_id,
            )
            processed = False

        if not processed:
            stop_event.wait(settings.experiment_worker_poll_seconds)

    logger.info("experiment_worker_stopped", worker_id=resolved_worker_id)


def main() -> None:
    """CLI entry point: ``python -m app.experiments.worker``."""
    configure_logging()
    stop_event = Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    run_worker(stop_event)


if __name__ == "__main__":
    main()
