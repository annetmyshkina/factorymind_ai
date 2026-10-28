import math

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.monitoring.metrics import METRICS
from app.monitoring.models import EquipmentDeviation, MonitoringRule
from app.telemetry.models import EquipmentTelemetry

logger = structlog.get_logger(__name__)


class InvalidMonitoringRuleError(ValueError):
    """Правило мониторинга содержит неподдерживаемые данные."""


def evaluate_telemetry(
    db: Session,
    telemetry: EquipmentTelemetry,
) -> list[EquipmentDeviation]:
    """Проверяет телеметрию и добавляет найденные отклонения в сессию."""

    rules = db.scalars(
        select(MonitoringRule).where(
            MonitoringRule.equipment_id == telemetry.equipment_id,
            MonitoringRule.is_active.is_(True),
        ),
    ).all()

    deviations: list[EquipmentDeviation] = []

    for rule in rules:
        metric = METRICS.get(rule.metric_name)

        if metric is None:
            logger.error(
                "invalid_rule_metric",
                rule_id=rule.id,
                metric_name=rule.metric_name,
            )
            raise InvalidMonitoringRuleError(
                f"Неизвестная метрика в правиле {rule.id}",
            )

        if rule.operator not in metric.allowed_operators:
            logger.error(
                "invalid_rule_operator",
                rule_id=rule.id,
                operator=rule.operator,
            )
            raise InvalidMonitoringRuleError(
                f"Неподдерживаемый оператор в правиле {rule.id}",
            )

        observed_value = getattr(telemetry, rule.metric_name)

        # Не проверяем отсутствующие значения.
        if observed_value is None:
            continue

        if isinstance(observed_value, bool) or not isinstance(
            observed_value,
            (int, float),
        ):
            raise InvalidMonitoringRuleError(
                f"Метрика {rule.metric_name} не является числовой",
            )

        if not math.isfinite(observed_value):
            raise InvalidMonitoringRuleError(
                f"Метрика {rule.metric_name} содержит неконечное значение",
            )

        if rule.operator == "gt":
            triggered = observed_value > rule.threshold_value
        else:
            triggered = observed_value < rule.threshold_value

        if not triggered:
            continue

        deviation = EquipmentDeviation(
            equipment_id=telemetry.equipment_id,
            telemetry_id=telemetry.id,
            rule_id=rule.id,
            metric_name=rule.metric_name,
            observed_value=observed_value,
            threshold_value=rule.threshold_value,
            message=(
                f"Правило «{rule.name}»: "
                f"{metric.name} = {observed_value:.4g} {metric.unit}; "
                f"порог = {rule.threshold_value:.4g} {metric.unit}; "
                f"условие = {rule.operator}"
            ),
        )

        db.add(deviation)
        deviations.append(deviation)

    return deviations
