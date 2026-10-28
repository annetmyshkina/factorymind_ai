from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.monitoring.metrics import METRICS

Operator = Literal["gt", "lt"]


class MonitoringRuleCreate(BaseModel):
    """Данные для создания правила мониторинга."""

    name: str = Field(min_length=1, max_length=100)
    metric_name: str = Field(min_length=1, max_length=100)
    operator: Operator
    threshold_value: float = Field(allow_inf_nan=False)
    description: str | None = None

    @field_validator("name", "metric_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value

    @field_validator("metric_name")
    @classmethod
    def validate_metric_name(cls, value: str) -> str:
        if value not in METRICS:
            raise ValueError("Метрика не поддерживается")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("threshold_value")
    @classmethod
    def validate_finite_threshold(cls, value: float) -> float:
        if not (-float("inf") < value < float("inf")):
            raise ValueError("Порог должен быть конечным числом")
        return value

    @field_validator("operator")
    @classmethod
    def validate_metric_operator(
        cls,
        value: Operator,
        info,
    ) -> Operator:
        metric_name = info.data.get("metric_name")
        if metric_name in METRICS:
            if value not in METRICS[metric_name].allowed_operators:
                raise ValueError("Оператор не поддерживается для этой метрики")
        return value


class MonitoringRuleResponse(BaseModel):
    """Правило мониторинга в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    name: str
    metric_name: str
    operator: Operator
    threshold_value: float
    description: str | None
    is_active: bool
    created_at: AwareDatetime


class EquipmentDeviationResponse(BaseModel):
    """Отклонение в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    telemetry_id: int | None
    rule_id: int | None
    metric_name: str
    observed_value: float
    threshold_value: float
    message: str
    detected_at: AwareDatetime
    is_resolved: bool
