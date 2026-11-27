"""MQTT- и HTTP-адаптеры транспорта симулятора."""

import json
from dataclasses import dataclass
from threading import Event
from types import TracebackType
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import paho.mqtt.client as mqtt

from simulator.core import TelemetryEvent, render_topic


@dataclass(frozen=True, slots=True)
class HTTPTarget:
    equipment_id: int
    api_key: str

    def __post_init__(self) -> None:
        if self.equipment_id <= 0:
            raise ValueError("HTTP equipment ID must be positive")
        if not self.api_key:
            raise ValueError("HTTP API key must not be empty")


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


class HTTPPublisher:
    """Отправляет метрики в FastAPI с отдельным ключом каждого оборудования."""

    def __init__(
        self,
        *,
        base_url: str,
        targets: dict[str, HTTPTarget],
        timeout: float = 10,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        parsed = urlsplit(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("HTTP API base URL must use http or https")
        if parsed.query or parsed.fragment:
            raise ValueError("HTTP API base URL must not contain query or fragment")
        if not targets:
            raise ValueError("at least one HTTP target is required")
        if timeout <= 0:
            raise ValueError("HTTP timeout must be positive")
        self._base_url = normalized_url
        self._targets = targets
        self._timeout = timeout

    def __enter__(self) -> "HTTPPublisher":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def publish(self, event: TelemetryEvent) -> None:
        target = self._targets.get(event.equipment_code)
        if target is None:
            raise ValueError(
                f"HTTP target is not configured for {event.equipment_code}",
            )
        request = Request(
            (f"{self._base_url}/equipment/{target.equipment_id}/telemetry"),
            data=json.dumps(
                event.http_payload(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-Key": target.api_key,
            },
            method="POST",
        )

        for attempt in range(2):
            try:
                with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    if response.status != 201:
                        raise RuntimeError(
                            "HTTP telemetry returned unexpected status "
                            f"{response.status} for {event.equipment_code}",
                        )
                    return
            except HTTPError as exc:
                retryable = exc.code in {408, 429} or exc.code >= 500
                if attempt == 0 and retryable:
                    continue
                raise RuntimeError(
                    "HTTP telemetry rejected "
                    f"for {event.equipment_code} with status {exc.code}",
                ) from exc
            except (TimeoutError, URLError) as exc:
                if attempt == 0:
                    continue
                raise ConnectionError(
                    f"HTTP telemetry failed for {event.equipment_code}",
                ) from exc

        raise ConnectionError(f"HTTP telemetry failed for {event.equipment_code}")
