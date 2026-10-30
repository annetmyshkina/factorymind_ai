import logging
import os
import sys
from pathlib import Path

import structlog
from concurrent_log_handler import ConcurrentRotatingFileHandler

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_TO_FILES = os.getenv("LOG_TO_FILES", "true").lower() in ("1", "true", "yes")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", 10 * 1024 * 1024))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", 5))


def _build_formatter() -> structlog.stdlib.ProcessorFormatter:
    """Общий formatter для всех handlers (консоль + файлы)."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.dict_tracebacks,
        structlog.processors.EventRenamer("message"),
    ]

    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )


def _make_file_handler(filename: Path, level: int) -> logging.Handler:
    """Файловый handler, безопасный при нескольких процессах (воркерах)."""
    handler = ConcurrentRotatingFileHandler(
        filename=str(filename),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    return handler


def configure_logging() -> None:
    """Настраивает структурированное JSON-логирование приложения."""
    formatter = _build_formatter()
    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    if LOG_TO_FILES:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        app_handler = _make_file_handler(LOG_DIR / "app.log", logging.DEBUG)
        app_handler.setFormatter(formatter)
        handlers.append(app_handler)

        error_handler = _make_file_handler(LOG_DIR / "errors.log", logging.ERROR)
        error_handler.setFormatter(formatter)
        handlers.append(error_handler)

    logging.basicConfig(
        level=LOG_LEVEL,
        handlers=handlers,
        force=True,
    )

    # httpx / httpx2 / httpcore / httpcore2: INFO, чтобы видеть статусы и ретраи
    for name in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(name).setLevel(logging.INFO)

    # uvicorn: убираем собственные handlers, отдаём записи нашему ProcessorFormatter
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.dict_tracebacks,
            structlog.processors.EventRenamer("message"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
