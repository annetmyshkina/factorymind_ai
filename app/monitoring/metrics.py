from dataclasses import dataclass
from typing import Literal

Operator = Literal["gt", "lt"]


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """Описание метрики, доступной для мониторинга."""

    name: str
    unit: str
    allowed_operators: frozenset[Operator]


DEFAULT_OPERATORS = frozenset[Operator]({"gt", "lt"})

METRICS: dict[str, MetricDefinition] = {
    "temperature_c": MetricDefinition(
        name="Температура",
        unit="°C",
        allowed_operators=DEFAULT_OPERATORS,
    ),
    "vibration_mm_s": MetricDefinition(
        name="Вибрация",
        unit="мм/с",
        allowed_operators=DEFAULT_OPERATORS,
    ),
    "ambient_temperature_c": MetricDefinition(
        name="Температура окружающей среды",
        unit="°C",
        allowed_operators=DEFAULT_OPERATORS,
    ),
    "suction_pressure_kpa_g": MetricDefinition(
        name="Давление на всасывании",
        unit="кПа (избыточное)",
        allowed_operators=DEFAULT_OPERATORS,
    ),
    "discharge_pressure_kpa_g": MetricDefinition(
        name="Давление нагнетания",
        unit="кПа (избыточное)",
        allowed_operators=DEFAULT_OPERATORS,
    ),
    "compressor_current_a": MetricDefinition(
        name="Ток компрессора",
        unit="А",
        allowed_operators=DEFAULT_OPERATORS,
    ),
    "compressor_vsd_frequency_hz": MetricDefinition(
        name="Частота преобразователя компрессора",
        unit="Гц",
        allowed_operators=DEFAULT_OPERATORS,
    ),
    "coolant_flow_rate_m3_h": MetricDefinition(
        name="Расход охлаждающей жидкости",
        unit="м³/ч",
        allowed_operators=DEFAULT_OPERATORS,
    ),
}
