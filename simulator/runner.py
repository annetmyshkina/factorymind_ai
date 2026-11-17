"""Цикл симуляции, независимый от конкретного транспорта."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from simulator.core import Scenario, TelemetryEvent, TelemetryGenerator, scenario_at
from simulator.delivery import DeliveryPlanner, DeliveryPolicy

logger = logging.getLogger(__name__)


class Publisher(Protocol):
    def publish(self, event: TelemetryEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class SimulatorConfig:
    equipment_codes: tuple[str, ...]
    scenario: Scenario = Scenario.DEMO_CYCLE
    interval_seconds: float = 2
    steps: int = 0
    seed: int = 42
    delivery: DeliveryPolicy = DeliveryPolicy()

    def __post_init__(self) -> None:
        if not self.equipment_codes:
            raise ValueError("at least one equipment code is required")
        if len(set(self.equipment_codes)) != len(self.equipment_codes):
            raise ValueError("equipment codes must be unique")
        if any(
            not code or any(char in code for char in "/+#")
            for code in self.equipment_codes
        ):
            raise ValueError("equipment codes must be valid MQTT topic levels")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if self.steps < 0:
            raise ValueError("steps must be non-negative")


class SimulatorRunner:
    def __init__(self, config: SimulatorConfig, publisher: Publisher) -> None:
        self._config = config
        self._publisher = publisher
        self._generator = TelemetryGenerator(config.seed)
        self._planner = DeliveryPlanner(config.delivery, seed=config.seed + 1)

    def run_step(
        self,
        step: int,
        *,
        measured_at: datetime | None = None,
    ) -> int:
        point = scenario_at(self._config.scenario, step)
        timestamp = measured_at or datetime.now(UTC)
        deliveries = []

        for equipment_code in self._config.equipment_codes:
            event = self._generator.generate(
                equipment_code,
                scenario=point.scenario,
                step=point.step,
                measured_at=timestamp,
            )
            deliveries.extend(self._planner.submit(step, event))

        deliveries.extend(self._planner.release_due(step))
        for delivery in deliveries:
            self._publisher.publish(delivery.event)
            logger.info(
                "telemetry published equipment=%s scenario=%s event=%s%s%s",
                delivery.event.equipment_code,
                delivery.event.scenario,
                delivery.event.event_id,
                " duplicate" if delivery.duplicate else "",
                " delayed" if delivery.delayed else "",
            )
        return len(deliveries)

    def run(self) -> None:
        step = 0
        while self._config.steps == 0 or step < self._config.steps:
            self.run_step(step)
            step += 1
            if self._config.steps == 0 or step < self._config.steps:
                time.sleep(self._config.interval_seconds)
