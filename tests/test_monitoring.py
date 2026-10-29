import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.monitoring.metrics import METRICS
from app.monitoring.models import EquipmentDeviation, MonitoringRule
from app.monitoring.schemas import MonitoringRuleCreate
from app.telemetry.models import EquipmentTelemetry


def _create_rule(
    db_session: Session,
    equipment_id: int,
    *,
    name: str = "Test rule",
    metric_name: str = "temperature_c",
    operator: str = "gt",
    threshold_value: float = 80.0,
    is_active: bool = True,
) -> MonitoringRule:
    rule = MonitoringRule(
        equipment_id=equipment_id,
        name=name,
        metric_name=metric_name,
        operator=operator,
        threshold_value=threshold_value,
        is_active=is_active,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    return rule


def test_unknown_metric_rejected_by_schema() -> None:
    with pytest.raises(ValidationError, match="Метрика не поддерживается"):
        MonitoringRuleCreate(
            name="X",
            metric_name="nonexistent_metric",
            operator="gt",
            threshold_value=1.0,
        )


def test_invalid_operator_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        MonitoringRuleCreate(
            name="X",
            metric_name="temperature_c",
            operator="eq",  # type: ignore[arg-type]
            threshold_value=1.0,
        )


def test_invalid_operator_rejected_by_db(
    db_session: Session,
    equipment: dict,
) -> None:
    rule = MonitoringRule(
        equipment_id=equipment["id"],
        name="X",
        metric_name="temperature_c",
        operator="eq",  # не пройдёт CheckConstraint
        threshold_value=1.0,
    )
    db_session.add(rule)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_threshold_exceeded_creates_deviation(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0, operator="gt")

    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={"temperature_c": 85.0, "vibration_mm_s": 1.0},
    )
    assert response.status_code == 201

    deviations = db_session.query(EquipmentDeviation).all()
    assert len(deviations) == 1
    assert deviations[0].metric_name == "temperature_c"
    assert deviations[0].observed_value == 85.0
    assert deviations[0].threshold_value == 80.0


@pytest.mark.parametrize("operator", ["gt", "lt"])
def test_equal_to_threshold_no_deviation(
    client: TestClient,
    db_session: Session,
    equipment: dict,
    operator: str,
) -> None:
    _create_rule(db_session, equipment["id"], threshold_value=80.0, operator=operator)

    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={"temperature_c": 80.0, "vibration_mm_s": 1.0},
    )
    assert response.status_code == 201

    deviations = db_session.query(EquipmentDeviation).all()
    assert deviations == []


def test_inactive_rules_skipped(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    _create_rule(
        db_session,
        equipment["id"],
        threshold_value=80.0,
        is_active=False,
    )

    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={"temperature_c": 999.0, "vibration_mm_s": 1.0},
    )
    assert response.status_code == 201

    assert db_session.query(EquipmentDeviation).all() == []


def test_missing_metric_skipped(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    _create_rule(
        db_session,
        equipment["id"],
        metric_name="ambient_temperature_c",
        threshold_value=-100.0,  # заведомо ниже любого значения
        operator="gt",
    )

    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={"temperature_c": 78.5, "vibration_mm_s": 1.0},
    )
    assert response.status_code == 201

    assert db_session.query(EquipmentDeviation).all() == []


def test_invalid_rule_rolls_back_telemetry(
    client: TestClient,
    db_session: Session,
    equipment: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.monitoring import service as service_module

    def _raise(*args, **kwargs):
        raise service_module.InvalidMonitoringRuleError("test")

    monkeypatch.setattr(
        "app.telemetry.router.evaluate_telemetry",
        _raise,
    )

    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={"temperature_c": 85.0, "vibration_mm_s": 1.0},
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Ошибка конфигурации правил мониторинга"}

    assert db_session.query(EquipmentTelemetry).count() == 0


def test_measured_at_is_aware_utc(
    client: TestClient,
    db_session: Session,
    equipment: dict,
) -> None:
    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={"temperature_c": 78.5, "vibration_mm_s": 1.0},
    )
    assert response.status_code == 201

    telemetry = db_session.query(EquipmentTelemetry).one()
    assert telemetry.measured_at.tzinfo is not None
    assert telemetry.measured_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nan_inf_rejected(
    client: TestClient,
    equipment: dict,
    value: str,
) -> None:
    response = client.post(
        f"/equipment/{equipment['id']}/telemetry",
        json={"temperature_c": value, "vibration_mm_s": 1.0},
    )
    assert response.status_code == 422


def test_all_metrics_have_telemetry_columns() -> None:
    columns = {col.key for col in inspect(EquipmentTelemetry).columns}
    missing = set(METRICS) - columns
    assert not missing, f"Метрики без колонок в EquipmentTelemetry: {missing}"
