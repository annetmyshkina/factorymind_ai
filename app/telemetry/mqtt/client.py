import paho.mqtt.client as mqtt
import structlog
from sqlalchemy.orm import sessionmaker

from app.telemetry.mqtt.handler import handle_message

logger = structlog.get_logger(__name__)

TOPIC = "factorymind/equipment/+/telemetry"


class MQTTSubscriber:
    """Подписчик MQTT, запускаемый в фоновом потоке."""

    def __init__(self, session_factory: sessionmaker, host: str, port: int) -> None:
        self._session_factory = session_factory
        self._host = host
        self._port = port
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def start(self) -> None:
        self._client.connect(self._host, self._port)
        self._client.loop_start()
        logger.info("mqtt_subscriber_started", host=self._host, port=self._port)

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("mqtt_subscriber_stopped")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(TOPIC)
            logger.info("mqtt_subscribed", topic=TOPIC)
        else:
            logger.error("mqtt_connect_failed", reason_code=reason_code)

    def _on_message(self, client, userdata, msg):
        with self._session_factory() as db:
            try:
                handle_message(db, msg.payload)
            except Exception:
                db.rollback()
                logger.exception("mqtt_handler_error", topic=msg.topic)
