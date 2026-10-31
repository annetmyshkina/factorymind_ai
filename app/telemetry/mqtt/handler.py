import json

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.equipment.models import Equipment
from app.incidents.automation import ensure_incident_for_deviation
from app.monitoring.service import evaluate_telemetry
from app.telemetry.models import EquipmentTelemetry, ProcessedMQTTEvent
from app.telemetry.mqtt.schemas import MQTTTelemetryMessage

logger = structlog.get_logger(__name__)


def handle_message(db: Session, payload: bytes) -> None:
    """Обрабатывает одно MQTT-сообщение."""
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("mqtt_invalid_json", payload=payload[:200])
        return

    try:
        message = MQTTTelemetryMessage.model_validate(raw)
    except ValidationError as exc:
        logger.warning("mqtt_invalid_schema", errors=exc.errors())
        return

    if db.get(ProcessedMQTTEvent, message.event_id) is not None:
        logger.info("mqtt_duplicate_event", event_id=message.event_id)
        return

    equipment = db.scalar(
        select(Equipment).where(Equipment.code == message.equipment_code),
    )
    if equipment is None:
        logger.warning(
            "mqtt_unknown_equipment",
            equipment_code=message.equipment_code,
            event_id=message.event_id,
        )
        return

    telemetry = EquipmentTelemetry(
        equipment_id=equipment.id,
        measured_at=message.measured_at,
        temperature_c=message.temperature_c,
        vibration_mm_s=message.vibration_mm_s,
        ambient_temperature_c=message.ambient_temperature_c,
        suction_pressure_kpa_g=message.suction_pressure_kpa_g,
        discharge_pressure_kpa_g=message.discharge_pressure_kpa_g,
        compressor_current_a=message.compressor_current_a,
        compressor_vsd_frequency_hz=message.compressor_vsd_frequency_hz,
        coolant_flow_rate_m3_h=message.coolant_flow_rate_m3_h,
        compressor_running=message.compressor_running,
    )
    db.add(telemetry)
    db.add(ProcessedMQTTEvent(event_id=message.event_id))
    db.flush()
    for deviation in evaluate_telemetry(db, telemetry):
        ensure_incident_for_deviation(db, deviation)
    db.commit()

    logger.info(
        "mqtt_telemetry_saved",
        event_id=message.event_id,
        equipment_code=message.equipment_code,
    )
