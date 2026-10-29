"""Симулятор датчиков оборудования: публикует телеметрию в MQTT."""

import json
import random
import time
import uuid
from datetime import UTC, datetime

import paho.mqtt.client as mqtt

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
EQUIPMENT_CODE = "COOLER-001"
INTERVAL_SECONDS = 5


def build_message() -> dict:
    """Формирует одно сообщение телеметрии."""
    return {
        "event_id": str(uuid.uuid4()),
        "equipment_code": EQUIPMENT_CODE,
        "measured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "temperature_c": round(random.uniform(3.0, 12.0), 2),
        "vibration_mm_s": round(random.uniform(0.5, 5.0), 2),
        "ambient_temperature_c": round(random.uniform(15.0, 30.0), 2),
        "suction_pressure_kpa_g": round(random.uniform(280.0, 380.0), 2),
        "discharge_pressure_kpa_g": round(random.uniform(1300.0, 1600.0), 2),
        "compressor_current_a": round(random.uniform(30.0, 60.0), 2),
        "compressor_vsd_frequency_hz": round(random.uniform(30.0, 60.0), 2),
        "coolant_flow_rate_m3_h": round(random.uniform(8.0, 15.0), 2),
        "compressor_running": True,
    }


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    topic = f"factorymind/equipment/{EQUIPMENT_CODE}/telemetry"
    print(f"Публикую в {topic} каждые {INTERVAL_SECONDS}с. Ctrl+C — стоп.")

    try:
        while True:
            message = build_message()
            client.publish(topic, json.dumps(message))
            print(f"[{message['measured_at']}] {message['temperature_c']}°C")
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nОстановлен.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
