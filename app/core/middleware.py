import time
import uuid

import structlog

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "x-request-id"
_MAX_REQUEST_ID_LEN = 64


def _get_header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _safe_request_id(raw: str | None) -> str:
    """Принимаем входящий ID, только если он безопасен и разумной длины."""
    if raw and len(raw) <= _MAX_REQUEST_ID_LEN and raw.isprintable() and " " not in raw:
        return raw
    return str(uuid.uuid4())


class RequestContextMiddleware:
    """Pure ASGI middleware: request_id + контекст оборудования в structlog."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _safe_request_id(_get_header(scope, REQUEST_ID_HEADER.encode()))

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=scope.get("path"),
            method=scope.get("method"),
        )

        # Идентификаторы оборудования/датчика от шлюза — сразу в контекст,
        # чтобы все последующие логи (включая вызовы ИИ) их содержали.
        equipment_id = _get_header(scope, b"x-equipment-id")
        sensor_id = _get_header(scope, b"x-sensor-id")
        if equipment_id:
            structlog.contextvars.bind_contextvars(equipment_id=equipment_id)
        if sensor_id:
            structlog.contextvars.bind_contextvars(sensor_id=sensor_id)

        status_code: int | None = None
        start = time.perf_counter()

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "http_request_failed",
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
            raise
        else:
            logger.info(
                "http_request",
                status=status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
        finally:
            structlog.contextvars.clear_contextvars()
