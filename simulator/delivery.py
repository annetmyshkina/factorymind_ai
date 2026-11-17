"""Имитация особенностей доставки без изменения измерений."""

import random
from dataclasses import dataclass

from simulator.core import TelemetryEvent


@dataclass(frozen=True, slots=True)
class DeliveryPolicy:
    drop_rate: float = 0
    duplicate_rate: float = 0
    delay_rate: float = 0
    delay_steps: int = 2

    def __post_init__(self) -> None:
        for name in ("drop_rate", "duplicate_rate", "delay_rate"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.delay_steps < 1:
            raise ValueError("delay_steps must be positive")


@dataclass(frozen=True, slots=True)
class PlannedDelivery:
    event: TelemetryEvent
    duplicate: bool = False
    delayed: bool = False


class DeliveryPlanner:
    """Планирует потери, дубли и отложенную доставку детерминированно."""

    def __init__(self, policy: DeliveryPolicy, *, seed: int = 42) -> None:
        self._policy = policy
        self._random = random.Random(seed)
        self._pending: list[tuple[int, tuple[PlannedDelivery, ...]]] = []

    def submit(self, step: int, event: TelemetryEvent) -> list[PlannedDelivery]:
        ready = self.release_due(step)
        if self._random.random() < self._policy.drop_rate:
            return ready

        copies = (
            (
                PlannedDelivery(event),
                PlannedDelivery(event, duplicate=True),
            )
            if self._random.random() < self._policy.duplicate_rate
            else (PlannedDelivery(event),)
        )

        if self._random.random() < self._policy.delay_rate:
            delayed = tuple(
                PlannedDelivery(
                    item.event,
                    duplicate=item.duplicate,
                    delayed=True,
                )
                for item in copies
            )
            self._pending.append((step + self._policy.delay_steps, delayed))
            return ready
        return [*ready, *copies]

    def release_due(self, step: int) -> list[PlannedDelivery]:
        ready: list[PlannedDelivery] = []
        pending: list[tuple[int, tuple[PlannedDelivery, ...]]] = []
        for due_step, deliveries in self._pending:
            if due_step <= step:
                ready.extend(deliveries)
            else:
                pending.append((due_step, deliveries))
        self._pending = pending
        return ready
