from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.telemetry.mqtt.client import MQTTSubscriber

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    subscriber: MQTTSubscriber | None = None

    if settings.environment != "test":
        subscriber = MQTTSubscriber(
            session_factory=SessionLocal,
            host=settings.mqtt_host,
            port=settings.mqtt_port,
        )
        subscriber.start()
        app.state.mqtt_client = subscriber

    try:
        yield
    finally:
        if subscriber is not None:
            subscriber.stop()
            logger.info("mqtt_disconnected")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
app.include_router(api_router)
