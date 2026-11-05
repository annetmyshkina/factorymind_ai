from unittest.mock import Mock

import pytest

from app.telemetry.mqtt.client import MQTTSubscriber, equipment_code_from_topic


def test_subscriber_uses_configured_topic() -> None:
    subscriber = MQTTSubscriber(
        session_factory=Mock(),
        host="mqtt.test",
        port=1883,
        topic="plant/+/metrics",
    )
    client = Mock()

    subscriber._on_connect(client, None, None, 0, None)

    client.subscribe.assert_called_once_with("plant/+/metrics")


def test_equipment_code_is_extracted_from_configured_topic() -> None:
    assert (
        equipment_code_from_topic(
            "site/telemetry/+/values",
            "site/telemetry/COOLER-42/values",
        )
        == "COOLER-42"
    )
    assert (
        equipment_code_from_topic(
            "site/telemetry/+/values",
            "other/telemetry/COOLER-42/values",
        )
        is None
    )


@pytest.mark.parametrize(
    "topic",
    [
        "factorymind/equipment/telemetry",
        "factorymind/+/+/telemetry",
        "factorymind/equipment/#",
    ],
)
def test_subscriber_rejects_topic_without_single_equipment_level(
    topic: str,
) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        MQTTSubscriber(
            session_factory=Mock(),
            host="mqtt.test",
            port=1883,
            topic=topic,
        )
