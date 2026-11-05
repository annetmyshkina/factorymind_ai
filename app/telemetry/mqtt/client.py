import paho.mqtt.client as mqtt
import structlog
from sqlalchemy.orm import sessionmaker

from app.telemetry.mqtt.handler import handle_message

logger = structlog.get_logger(__name__)


def equipment_code_from_topic(topic_filter: str, topic: str) -> str | None:
    """Извлекает код оборудования из единственного `+` MQTT-фильтра."""
    filter_levels = topic_filter.split("/")
    topic_levels = topic.split("/")
    if len(filter_levels) != len(topic_levels):
        return None

    equipment_code: str | None = None
    for filter_level, topic_level in zip(filter_levels, topic_levels, strict=True):
        if filter_level == "+":
            if equipment_code is not None or not topic_level:
                return None
            equipment_code = topic_level
        elif filter_level == "#" or filter_level != topic_level:
            return None

    return equipment_code


class MQTTSubscriber:
    """Подписчик MQTT, запускаемый в фоновом потоке."""

    def __init__(
        self,
        session_factory: sessionmaker,
        host: str,
        port: int,
        topic: str,
    ) -> None:
        if topic.split("/").count("+") != 1 or "#" in topic.split("/"):
            raise ValueError("MQTT telemetry topic must contain exactly one '+' level")

        self._session_factory = session_factory
        self._host = host
        self._port = port
        self._topic = topic
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
            client.subscribe(self._topic)
            logger.info("mqtt_subscribed", topic=self._topic)
        else:
            logger.error("mqtt_connect_failed", reason_code=reason_code)

    def _on_message(self, client, userdata, msg):
        equipment_code = equipment_code_from_topic(self._topic, msg.topic)
        if equipment_code is None:
            logger.warning(
                "mqtt_unexpected_topic",
                topic=msg.topic,
                topic_filter=self._topic,
            )
            return

        with self._session_factory() as db:
            try:
                handle_message(
                    db,
                    msg.payload,
                    topic_equipment_code=equipment_code,
                )
            except Exception:
                db.rollback()
                logger.exception("mqtt_handler_error", topic=msg.topic)
