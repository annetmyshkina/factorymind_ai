import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from uuid import UUID

import pytest

from app.telemetry.mqtt.schemas import MQTTTelemetryMessage
from app.telemetry.schemas import TelemetryCreate
from simulator.cli import main, parse_http_targets
from simulator.core import (
    Scenario,
    TelemetryGenerator,
    render_topic,
    scenario_at,
)
from simulator.delivery import DeliveryPlanner, DeliveryPolicy
from simulator.publisher import HTTPPublisher, HTTPTarget, MQTTPublisher
from simulator.runner import SimulatorConfig, SimulatorRunner

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
RUN_ID = UUID("12345678-1234-5678-1234-567812345678")


class FakePublisher:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


def _event(*, seed: int = 42):
    return TelemetryGenerator(seed, run_id=RUN_ID).generate(
        "CMP-01",
        scenario=Scenario.NORMAL,
        step=0,
        measured_at=NOW,
    )


def test_generated_event_matches_existing_mqtt_contract() -> None:
    event = _event()

    message = MQTTTelemetryMessage.model_validate_json(event.to_json())

    assert message.event_id == event.event_id
    assert message.equipment_code == "CMP-01"
    assert message.measured_at == NOW
    assert "scenario" not in json.loads(event.to_json())


def test_generated_event_matches_existing_http_contract() -> None:
    event = _event()

    message = TelemetryCreate.model_validate(event.http_payload())

    assert message.temperature_c == event.temperature_c
    assert message.vibration_mm_s == event.vibration_mm_s
    assert "event_id" not in event.http_payload()
    assert "equipment_code" not in event.http_payload()


def test_generation_is_reproducible_with_same_seed() -> None:
    first = _event(seed=7)
    second = _event(seed=7)

    assert first == second


def test_new_run_does_not_reuse_event_id() -> None:
    first = TelemetryGenerator(7).generate(
        "CMP-01",
        scenario=Scenario.NORMAL,
        step=0,
        measured_at=NOW,
    )
    second = TelemetryGenerator(7).generate(
        "CMP-01",
        scenario=Scenario.NORMAL,
        step=0,
        measured_at=NOW,
    )

    assert first.event_id != second.event_id


def test_scenarios_have_distinct_synthetic_ranges() -> None:
    values = {
        scenario: TelemetryGenerator(11).generate(
            "CMP-01",
            scenario=scenario,
            step=0,
            measured_at=NOW,
        )
        for scenario in (Scenario.NORMAL, Scenario.WARNING, Scenario.CRITICAL)
    }

    assert (
        values[Scenario.NORMAL].temperature_c
        < values[Scenario.WARNING].temperature_c
        < values[Scenario.CRITICAL].temperature_c
    )
    assert (
        values[Scenario.NORMAL].vibration_mm_s
        < values[Scenario.WARNING].vibration_mm_s
        < values[Scenario.CRITICAL].vibration_mm_s
    )


def test_recovery_returns_towards_normal_values() -> None:
    generator = TelemetryGenerator(17)

    beginning = generator.generate(
        "CMP-01",
        scenario=Scenario.RECOVERY,
        step=0,
        measured_at=NOW,
    )
    end = generator.generate(
        "CMP-01",
        scenario=Scenario.RECOVERY,
        step=19,
        measured_at=NOW,
    )

    assert end.temperature_c < beginning.temperature_c - 25
    assert end.vibration_mm_s < beginning.vibration_mm_s - 5


@pytest.mark.parametrize(
    ("step", "expected", "phase_step"),
    [
        (0, Scenario.NORMAL, 0),
        (19, Scenario.NORMAL, 19),
        (20, Scenario.WARNING, 0),
        (30, Scenario.CRITICAL, 0),
        (40, Scenario.RECOVERY, 0),
        (59, Scenario.RECOVERY, 19),
        (60, Scenario.NORMAL, 0),
    ],
)
def test_demo_cycle_transitions(
    step: int,
    expected: Scenario,
    phase_step: int,
) -> None:
    point = scenario_at(Scenario.DEMO_CYCLE, step)

    assert point.scenario is expected
    assert point.step == phase_step


def test_topic_uses_equipment_code() -> None:
    assert (
        render_topic("factorymind/equipment/+/telemetry", "CMP-01")
        == "factorymind/equipment/CMP-01/telemetry"
    )


@pytest.mark.parametrize(
    ("topic", "equipment"),
    [
        ("factorymind/equipment/telemetry", "CMP-01"),
        ("factorymind/+/+/telemetry", "CMP-01"),
        ("factorymind/#", "CMP-01"),
        ("factorymind/+/telemetry", "CMP/01"),
    ],
)
def test_invalid_topic_or_equipment_is_rejected(
    topic: str,
    equipment: str,
) -> None:
    with pytest.raises(ValueError):
        render_topic(topic, equipment)


def test_delivery_can_drop_message() -> None:
    planner = DeliveryPlanner(DeliveryPolicy(drop_rate=1), seed=1)

    assert planner.submit(0, _event()) == []


def test_delivery_can_repeat_same_event_id() -> None:
    planner = DeliveryPlanner(DeliveryPolicy(duplicate_rate=1), seed=1)

    deliveries = planner.submit(0, _event())

    assert len(deliveries) == 2
    assert deliveries[0].event.event_id == deliveries[1].event.event_id
    assert deliveries[1].duplicate is True


def test_delivery_can_release_message_out_of_order() -> None:
    planner = DeliveryPlanner(
        DeliveryPolicy(delay_rate=1, delay_steps=2),
        seed=1,
    )
    event = _event()

    assert planner.submit(0, event) == []
    assert planner.release_due(1) == []
    released = planner.release_due(2)

    assert [item.event for item in released] == [event]
    assert released[0].delayed is True


def test_runner_publishes_without_database_or_broker() -> None:
    publisher = FakePublisher()
    runner = SimulatorRunner(
        SimulatorConfig(
            equipment_codes=("CMP-01", "PMP-07"),
            scenario=Scenario.NORMAL,
            seed=3,
        ),
        publisher,
    )

    count = runner.run_step(0, measured_at=NOW)

    assert count == 2
    assert [event.equipment_code for event in publisher.events] == [
        "CMP-01",
        "PMP-07",
    ]


def test_finite_runner_stops_after_configured_steps() -> None:
    publisher = FakePublisher()
    runner = SimulatorRunner(
        SimulatorConfig(
            equipment_codes=("CMP-01",),
            scenario=Scenario.NORMAL,
            steps=1,
        ),
        publisher,
    )

    runner.run()

    assert len(publisher.events) == 1


def test_mqtt_publisher_uses_rendered_topic_and_qos() -> None:
    client = Mock()
    client.connect.return_value = 0
    client.loop_start.side_effect = lambda: client.on_connect(
        client,
        None,
        None,
        0,
        None,
    )
    publish_result = Mock(rc=0)
    publish_result.is_published.return_value = True
    client.publish.return_value = publish_result
    event = _event()

    with patch("simulator.publisher.mqtt.Client", return_value=client):
        with MQTTPublisher(
            host="mqtt.test",
            port=1883,
            topic="plant/+/telemetry",
        ) as publisher:
            publisher.publish(event)

    client.connect.assert_called_once_with("mqtt.test", 1883)
    client.publish.assert_called_once_with(
        "plant/CMP-01/telemetry",
        event.to_json(),
        qos=1,
    )
    publish_result.wait_for_publish.assert_called_once_with(timeout=10)
    client.loop_start.assert_called_once_with()
    client.reconnect_delay_set.assert_called_once_with(min_delay=1, max_delay=30)
    client.loop_stop.assert_called_once_with()
    client.disconnect.assert_called_once_with()


def test_mqtt_publish_retries_same_event_after_disconnect() -> None:
    client = Mock()
    client.connect.return_value = 0
    client.loop_start.side_effect = lambda: client.on_connect(
        client,
        None,
        None,
        0,
        None,
    )
    failed = Mock(rc=4)
    failed.wait_for_publish.side_effect = RuntimeError("not connected")
    succeeded = Mock(rc=0)
    succeeded.is_published.return_value = True
    client.publish.side_effect = [failed, succeeded]
    connected = Mock()
    connected.wait.return_value = True
    event = _event()

    with (
        patch("simulator.publisher.Event", return_value=connected),
        patch("simulator.publisher.mqtt.Client", return_value=client),
    ):
        with MQTTPublisher(
            host="mqtt.test",
            port=1883,
            topic="plant/+/telemetry",
        ) as publisher:
            publisher.publish(event)

    assert client.publish.call_count == 2
    assert client.publish.call_args_list[0] == client.publish.call_args_list[1]


def test_default_mqtt_client_ids_are_unique() -> None:
    with patch("simulator.publisher.mqtt.Client") as client_factory:
        MQTTPublisher(host="mqtt.test", port=1883, topic="plant/+/telemetry")
        MQTTPublisher(host="mqtt.test", port=1883, topic="plant/+/telemetry")

    first_id = client_factory.call_args_list[0].kwargs["client_id"]
    second_id = client_factory.call_args_list[1].kwargs["client_id"]
    assert first_id.startswith("factorymind-simulator-")
    assert second_id.startswith("factorymind-simulator-")
    assert first_id != second_id


def test_http_publisher_uses_equipment_id_key_and_metric_payload() -> None:
    response = Mock(status=201)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    event = _event()

    with patch("simulator.publisher.urlopen", return_value=response) as send:
        with HTTPPublisher(
            base_url="http://api.test/",
            targets={
                "CMP-01": HTTPTarget(
                    equipment_id=19,
                    api_key="fmk_test_secret",
                ),
            },
        ) as publisher:
            publisher.publish(event)

    request = send.call_args.args[0]
    assert request.full_url == "http://api.test/equipment/19/telemetry"
    assert request.method == "POST"
    assert request.get_header("X-api-key") == "fmk_test_secret"
    assert json.loads(request.data) == event.http_payload()
    assert send.call_args.kwargs == {"timeout": 10}


def test_http_publisher_retries_server_error_without_exposing_key() -> None:
    response = Mock(status=201)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    error = HTTPError("http://api.test", 503, "unavailable", {}, None)
    target = HTTPTarget(equipment_id=19, api_key="secret-must-not-leak")

    with patch(
        "simulator.publisher.urlopen",
        side_effect=[error, response],
    ) as send:
        HTTPPublisher(
            base_url="http://api.test",
            targets={"CMP-01": target},
        ).publish(_event())

    assert send.call_count == 2

    rejected = HTTPError("http://api.test", 401, "unauthorized", {}, None)
    with (
        patch("simulator.publisher.urlopen", side_effect=rejected),
        pytest.raises(RuntimeError) as exc_info,
    ):
        HTTPPublisher(
            base_url="http://api.test",
            targets={"CMP-01": target},
        ).publish(_event())
    assert "secret-must-not-leak" not in str(exc_info.value)


def test_http_targets_json_is_strictly_validated() -> None:
    targets = parse_http_targets(
        json.dumps(
            {
                "CMP-01": {
                    "equipment_id": 19,
                    "api_key": "fmk_key",
                },
            },
        ),
    )

    assert targets == {
        "CMP-01": HTTPTarget(equipment_id=19, api_key="fmk_key"),
    }

    with pytest.raises(ValueError):
        parse_http_targets('{"CMP-01":{"equipment_id":19}}')


def test_cli_runs_finite_scenario_without_real_broker() -> None:
    publisher = FakePublisher()

    with patch("simulator.cli.MQTTPublisher", return_value=publisher):
        result = main(
            [
                "--equipment",
                "CMP-01,CMP-02",
                "--scenario",
                "critical",
                "--steps",
                "1",
            ],
        )

    assert result == 0
    assert len(publisher.events) == 2
    assert {event.scenario for event in publisher.events} == {"critical"}


def test_cli_runs_http_transport_with_configured_target(tmp_path: Path) -> None:
    publisher = FakePublisher()
    targets = json.dumps(
        {"CMP-01": {"equipment_id": 19, "api_key": "fmk_key"}},
    )
    targets_file = tmp_path / "http-targets.json"
    targets_file.write_text(targets, encoding="utf-8")

    with (
        patch("simulator.cli.HTTPPublisher", return_value=publisher) as factory,
    ):
        result = main(
            [
                "--transport",
                "http",
                "--equipment",
                "CMP-01",
                "--steps",
                "1",
                "--api-base-url",
                "http://api.test",
                "--http-targets-file",
                str(targets_file),
            ],
        )

    assert result == 0
    factory.assert_called_once_with(
        base_url="http://api.test",
        targets={"CMP-01": HTTPTarget(equipment_id=19, api_key="fmk_key")},
        timeout=10,
    )
    assert len(publisher.events) == 1


def test_cli_rejects_delivery_faults_for_http_transport() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--transport",
                "http",
                "--equipment",
                "CMP-01",
                "--steps",
                "1",
                "--duplicate-rate",
                "1",
            ],
        )


@pytest.mark.parametrize(
    "equipment_codes",
    [(), ("CMP-01", "CMP-01"), ("CMP/01",)],
)
def test_invalid_equipment_configuration_is_rejected(
    equipment_codes: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        SimulatorConfig(equipment_codes=equipment_codes)


@pytest.mark.parametrize(
    "values",
    [
        {"drop_rate": -0.1},
        {"duplicate_rate": 1.1},
        {"delay_rate": 2},
        {"delay_steps": 0},
    ],
)
def test_invalid_delivery_policy_is_rejected(values: dict) -> None:
    with pytest.raises(ValueError):
        DeliveryPolicy(**values)
