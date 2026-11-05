import json

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.equipment.models import Equipment
from app.telemetry.models import EquipmentTelemetry, ProcessedMQTTEvent
from app.telemetry.mqtt.handler import handle_message
from app.telemetry.mqtt.schemas import MQTTTelemetryMessage

NUMERIC_METRICS = (
    "temperature_c",
    "vibration_mm_s",
    "ambient_temperature_c",
    "suction_pressure_kpa_g",
    "discharge_pressure_kpa_g",
    "compressor_current_a",
    "compressor_vsd_frequency_hz",
    "coolant_flow_rate_m3_h",
)


def _payload(**overrides) -> dict:
    payload = {
        "event_id": "mqtt-validation",
        "equipment_code": "MQTT-VALIDATION",
        "measured_at": "2026-11-05T00:00:00Z",
        "temperature_c": 20.0,
        "vibration_mm_s": 1.0,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("metric_name", NUMERIC_METRICS)
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_mqtt_rejects_non_finite_metrics(metric_name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        MQTTTelemetryMessage.model_validate(
            _payload(**{metric_name: value}),
        )


def test_mqtt_accepts_extreme_finite_metrics() -> None:
    extreme = 1e308
    message = MQTTTelemetryMessage.model_validate(
        _payload(**{metric_name: extreme for metric_name in NUMERIC_METRICS}),
    )

    for metric_name in NUMERIC_METRICS:
        assert getattr(message, metric_name) == extreme


def test_invalid_mqtt_message_is_not_persisted(db_session: Session) -> None:
    equipment = Equipment(
        code="MQTT-VALIDATION",
        name="MQTT validation",
        equipment_type="test",
        location="test",
    )
    db_session.add(equipment)
    db_session.commit()

    handle_message(
        db_session,
        json.dumps(_payload(temperature_c="NaN")).encode(),
    )

    telemetry_count = db_session.scalar(
        select(func.count()).select_from(EquipmentTelemetry),
    )
    processed_count = db_session.scalar(
        select(func.count()).select_from(ProcessedMQTTEvent),
    )
    assert telemetry_count == 0
    assert processed_count == 0
