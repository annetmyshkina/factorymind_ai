"""Тонкий MQTT-адаптер симулятора."""

from threading import Event
from types import TracebackType
from uuid import uuid4

import paho.mqtt.client as mqtt

from simulator.core import TelemetryEvent, render_topic


class MQTTPublisher:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        topic: str,
        client_id: str | None = None,
        qos: int = 1,
        connection_timeout: float = 10,
    ) -> None:
        if not host:
            raise ValueError("MQTT host must not be empty")
        if not 1 <= port <= 65_535:
            raise ValueError("MQTT port must be between 1 and 65535")
        if qos not in {0, 1, 2}:
            raise ValueError("MQTT QoS must be 0, 1 or 2")
        if connection_timeout <= 0:
            raise ValueError("connection timeout must be positive")
        render_topic(topic, "VALIDATION")
        self._host = host
        self._port = port
        self._topic = topic
        self._qos = qos
        self._connection_timeout = connection_timeout
        self._connected = Event()
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id or f"factorymind-simulator-{uuid4().hex[:12]}",
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            self._connected.set()
        else:
            self._connected.clear()

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ) -> None:
        self._connected.clear()

    def __enter__(self) -> "MQTTPublisher":
        result = self._client.connect(self._host, self._port)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT connect failed with code {result}")
        self._client.loop_start()
        if not self._connected.wait(self._connection_timeout):
            self._client.loop_stop()
            self._client.disconnect()
            raise TimeoutError("MQTT connection confirmation timed out")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, event: TelemetryEvent) -> None:
        topic = render_topic(self._topic, event.equipment_code)
        payload = event.to_json()
        error: Exception | None = None

        for attempt in range(2):
            if not self._connected.wait(self._connection_timeout):
                raise ConnectionError("MQTT connection is unavailable") from error
            result = self._client.publish(topic, payload, qos=self._qos)
            try:
                result.wait_for_publish(timeout=self._connection_timeout)
            except RuntimeError as exc:
                error = exc
                self._connected.clear()
                if attempt == 0:
                    continue
                raise ConnectionError("MQTT publish failed after reconnect") from exc
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed with code {result.rc}")
            if not result.is_published():
                raise TimeoutError("MQTT publish confirmation timed out")
            return

        raise ConnectionError("MQTT publish failed") from error
