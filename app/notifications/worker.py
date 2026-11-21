"""Отдельный процесс доставки Telegram outbox."""

import os
import signal
import socket
from threading import Event
from uuid import uuid4

import structlog
from prometheus_client import start_http_server

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.notifications.queue import (
    process_next_notification,
    recover_expired_notifications,
    update_queue_metrics,
)
from app.notifications.telegram import TelegramClient
from app.observability.metrics import (
    NOTIFICATION_WORKER_ITERATION_ERRORS,
    NOTIFICATION_WORKER_UP,
)

logger = structlog.get_logger(__name__)


def make_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"


def run_worker(
    stop_event: Event,
    client: TelegramClient,
    *,
    worker_id: str | None = None,
) -> None:
    resolved_worker_id = worker_id or make_worker_id()
    logger.info("notification_worker_started", worker_id=resolved_worker_id)
    NOTIFICATION_WORKER_UP.set(1)
    try:
        while not stop_event.is_set():
            try:
                with SessionLocal() as db:
                    recover_expired_notifications(db)
                processed = process_next_notification(
                    SessionLocal,
                    resolved_worker_id,
                    client,
                )
                with SessionLocal() as db:
                    update_queue_metrics(db)
            except Exception:
                NOTIFICATION_WORKER_ITERATION_ERRORS.inc()
                logger.exception(
                    "notification_worker_iteration_failed",
                    worker_id=resolved_worker_id,
                )
                processed = False

            if not processed:
                stop_event.wait(settings.notification_worker_poll_seconds)
    finally:
        NOTIFICATION_WORKER_UP.set(0)
    logger.info("notification_worker_stopped", worker_id=resolved_worker_id)


def main() -> None:
    """CLI entry point: ``python -m app.notifications.worker``."""
    configure_logging()
    if not settings.telegram_notifications_enabled:
        logger.warning("telegram_notifications_disabled")
        return

    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    assert token is not None and chat_id is not None

    stop_event = Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    metrics_server, metrics_thread = start_http_server(
        settings.notification_worker_metrics_port,
        addr=settings.notification_worker_metrics_host,
    )
    client = TelegramClient(
        bot_token=token.get_secret_value(),
        chat_id=chat_id,
        base_url=settings.telegram_api_base_url,
        timeout=settings.telegram_timeout_seconds,
    )
    logger.info(
        "notification_worker_metrics_started",
        host=settings.notification_worker_metrics_host,
        port=settings.notification_worker_metrics_port,
    )
    try:
        run_worker(stop_event, client)
    finally:
        client.close()
        metrics_server.shutdown()
        metrics_server.server_close()
        metrics_thread.join(timeout=5)


if __name__ == "__main__":
    main()
