"""Детерминированная генерация синтетической телеметрии."""

import json
import math
import random
import zlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4, uuid5


class Scenario(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    RECOVERY = "recovery"
    DEMO_CYCLE = "demo_cycle"


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    event_id: str
    equipment_code: str
    measured_at: str
    temperature_c: float
    vibration_mm_s: float
    ambient_temperature_c: float
    suction_pressure_kpa_g: float
    discharge_pressure_kpa_g: float
    compressor_current_a: float
    compressor_vsd_frequency_hz: float
    coolant_flow_rate_m3_h: float
    compressor_running: bool
    scenario: str

    def mqtt_payload(self) -> dict[str, str | float | bool]:
        """Возвращает только поля действующего MQTT-контракта."""
        payload = asdict(self)
        payload.pop("scenario")
        return payload

    def http_payload(self) -> dict[str, float | bool]:
        """Возвращает только метрики действующего HTTP-контракта."""
        return {
            "temperature_c": self.temperature_c,
            "vibration_mm_s": self.vibration_mm_s,
            "ambient_temperature_c": self.ambient_temperature_c,
            "suction_pressure_kpa_g": self.suction_pressure_kpa_g,
            "discharge_pressure_kpa_g": self.discharge_pressure_kpa_g,
            "compressor_current_a": self.compressor_current_a,
            "compressor_vsd_frequency_hz": self.compressor_vsd_frequency_hz,
            "coolant_flow_rate_m3_h": self.coolant_flow_rate_m3_h,
            "compressor_running": self.compressor_running,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.mqtt_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class ScenarioPoint:
    scenario: Scenario
    step: int


_CYCLE_PHASES: tuple[tuple[Scenario, int], ...] = (
    (Scenario.NORMAL, 20),
    (Scenario.WARNING, 10),
    (Scenario.CRITICAL, 10),
    (Scenario.RECOVERY, 20),
)


def scenario_at(mode: Scenario, step: int) -> ScenarioPoint:
    """Определяет текущую фазу и локальный шаг сценария."""
    if step < 0:
        raise ValueError("step must be non-negative")
    if mode is not Scenario.DEMO_CYCLE:
        return ScenarioPoint(mode, step)

    cycle_step = step % sum(duration for _, duration in _CYCLE_PHASES)
    for scenario, duration in _CYCLE_PHASES:
        if cycle_step < duration:
            return ScenarioPoint(scenario, cycle_step)
        cycle_step -= duration
    raise RuntimeError("invalid demo cycle")


class TelemetryGenerator:
    """Создаёт воспроизводимые показания без доступа к приложению или БД."""

    def __init__(self, seed: int = 42, *, run_id: UUID | None = None) -> None:
        self._random = random.Random(seed)
        self._run_id = run_id or uuid4()
        self._event_sequence = 0

    def generate(
        self,
        equipment_code: str,
        *,
        scenario: Scenario,
        step: int,
        measured_at: datetime | None = None,
    ) -> TelemetryEvent:
        if not equipment_code or any(char in equipment_code for char in "/+#"):
            raise ValueError("equipment code must be a non-empty MQTT topic level")
        if step < 0:
            raise ValueError("step must be non-negative")

        phase = self._equipment_phase(equipment_code)
        wave = math.sin(step / 3 + phase)
        jitter = self._random.uniform(-0.25, 0.25)
        temperature, vibration, current, coolant = self._scenario_values(
            scenario,
            step,
            wave,
            jitter,
        )
        timestamp = (measured_at or datetime.now(UTC)).astimezone(UTC)

        event_id = uuid5(
            self._run_id,
            f"{self._event_sequence}:{equipment_code}:{scenario.value}:{step}",
        )
        self._event_sequence += 1

        return TelemetryEvent(
            event_id=str(event_id),
            equipment_code=equipment_code,
            measured_at=timestamp.isoformat().replace("+00:00", "Z"),
            temperature_c=round(temperature, 2),
            vibration_mm_s=round(max(0, vibration), 2),
            ambient_temperature_c=round(23.5 + wave * 0.7 + jitter, 2),
            suction_pressure_kpa_g=round(96 + wave * 2.5, 2),
            discharge_pressure_kpa_g=round(730 + wave * 18, 2),
            compressor_current_a=round(max(0, current), 2),
            compressor_vsd_frequency_hz=round(49.5 + wave * 0.8, 2),
            coolant_flow_rate_m3_h=round(max(0, coolant), 2),
            compressor_running=True,
            scenario=scenario.value,
        )

    @staticmethod
    def _equipment_phase(equipment_code: str) -> float:
        return (zlib.crc32(equipment_code.encode()) % 628) / 100

    @staticmethod
    def _scenario_values(
        scenario: Scenario,
        step: int,
        wave: float,
        jitter: float,
    ) -> tuple[float, float, float, float]:
        if scenario is Scenario.NORMAL:
            return (
                63 + wave * 1.8 + jitter,
                2.1 + wave * 0.25 + jitter / 3,
                88 + wave * 4,
                12.5 + wave * 0.5,
            )
        if scenario is Scenario.WARNING:
            return (
                78 + wave * 2.2 + jitter,
                5.2 + wave * 0.45 + jitter / 3,
                102 + wave * 5,
                10.2 + wave * 0.4,
            )
        if scenario is Scenario.CRITICAL:
            return (
                92 + wave * 2.8 + jitter,
                8.4 + wave * 0.7 + jitter / 3,
                119 + wave * 7,
                7.1 + wave * 0.35,
            )
        if scenario is Scenario.RECOVERY:
            progress = min(step / 19, 1)
            return (
                92 - 29 * progress + wave * (1 - progress) + jitter,
                8.4 - 6.3 * progress + wave * 0.2 + jitter / 3,
                119 - 31 * progress + wave * 3,
                7.1 + 5.4 * progress + wave * 0.25,
            )
        raise ValueError(f"scenario {scenario!s} cannot generate telemetry directly")


def render_topic(topic_filter: str, equipment_code: str) -> str:
    """Подставляет код оборудования в единственный `+` MQTT-фильтра."""
    levels = topic_filter.split("/")
    if levels.count("+") != 1 or "#" in levels:
        raise ValueError("MQTT topic must contain exactly one '+' level")
    if not equipment_code or any(char in equipment_code for char in "/+#"):
        raise ValueError("equipment code must be one MQTT topic level")
    return "/".join(equipment_code if level == "+" else level for level in levels)
