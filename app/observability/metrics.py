"""Prometheus-метрики с ограниченной кардинальностью labels."""

from collections.abc import Mapping

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "factorymind_http_requests_total",
    "Количество завершённых HTTP-запросов.",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "factorymind_http_request_duration_seconds",
    "Длительность HTTP-запросов в секундах.",
    ("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

MQTT_MESSAGES = Counter(
    "factorymind_mqtt_messages_total",
    "Количество MQTT-сообщений по результату обработки.",
    ("outcome",),
)
MQTT_CONNECTED = Gauge(
    "factorymind_mqtt_connected",
    "Состояние соединения MQTT-подписчика: 1 — подключён, 0 — отключён.",
)

INCIDENTS_CREATED = Counter(
    "factorymind_incidents_created_total",
    "Количество созданных инцидентов.",
    ("source", "severity"),
)

LLM_CALLS = Counter(
    "factorymind_llm_calls_total",
    "Количество сохранённых вызовов LLM.",
    ("provider", "status", "error_type"),
)
LLM_CALL_DURATION = Histogram(
    "factorymind_llm_call_duration_seconds",
    "Длительность вызовов LLM в секундах.",
    ("provider", "status"),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
LLM_TOKENS = Counter(
    "factorymind_llm_tokens_total",
    "Количество токенов успешных LLM-вызовов.",
    ("provider", "direction"),
)

EXPERIMENT_RUNS_CLAIMED = Counter(
    "factorymind_experiment_runs_claimed_total",
    "Количество попыток, захваченных experiment worker-ом.",
)
EXPERIMENT_RUN_OUTCOMES = Counter(
    "factorymind_experiment_run_outcomes_total",
    "Результаты обработки попыток experiment worker-ом.",
    ("outcome",),
)
EXPERIMENT_LEASE_RECOVERIES = Counter(
    "factorymind_experiment_lease_recoveries_total",
    "Количество восстановленных просроченных lease.",
    ("outcome",),
)
EXPERIMENT_QUEUE_RUNS = Gauge(
    "factorymind_experiment_queue_runs",
    "Текущее количество experiment runs по статусам.",
    ("status",),
)
EXPERIMENT_WORKER_UP = Gauge(
    "factorymind_experiment_worker_up",
    "Состояние цикла experiment worker-а: 1 — работает, 0 — остановлен.",
)
EXPERIMENT_WORKER_ITERATION_ERRORS = Counter(
    "factorymind_experiment_worker_iteration_errors_total",
    "Количество необработанных ошибок итерации experiment worker-а.",
)

EXPERIMENT_RUN_STATUSES = ("pending", "running", "completed", "failed")

NOTIFICATIONS_ENQUEUED = Counter(
    "factorymind_notifications_enqueued_total",
    "Количество уведомлений, записанных в outbox.",
    ("event_type",),
)
NOTIFICATION_DELIVERIES = Counter(
    "factorymind_notification_deliveries_total",
    "Результаты попыток доставки уведомлений.",
    ("outcome",),
)
NOTIFICATION_LEASE_RECOVERIES = Counter(
    "factorymind_notification_lease_recoveries_total",
    "Количество восстановленных lease notification worker-а.",
    ("outcome",),
)
NOTIFICATION_QUEUE_ITEMS = Gauge(
    "factorymind_notification_queue_items",
    "Текущее количество уведомлений по статусам.",
    ("status",),
)
NOTIFICATION_WORKER_UP = Gauge(
    "factorymind_notification_worker_up",
    "Состояние notification worker-а: 1 — работает, 0 — остановлен.",
)
NOTIFICATION_WORKER_ITERATION_ERRORS = Counter(
    "factorymind_notification_worker_iteration_errors_total",
    "Количество необработанных ошибок notification worker-а.",
)

NOTIFICATION_STATUSES = ("pending", "running", "sent", "failed")


def observe_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Фиксирует HTTP-запрос без значений path-параметров в labels."""
    status = str(status_code)
    HTTP_REQUESTS.labels(method=method, route=route, status_code=status).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration_seconds)


def observe_mqtt_message(outcome: str) -> None:
    MQTT_MESSAGES.labels(outcome=outcome).inc()


def observe_incident_created(*, source: str, severity: str) -> None:
    INCIDENTS_CREATED.labels(source=source, severity=severity).inc()


def observe_llm_call(
    *,
    provider: str,
    status: str,
    latency_ms: int,
    error_type: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> None:
    """Фиксирует только уже сохранённый в журнале LLM-вызов."""
    LLM_CALLS.labels(
        provider=provider,
        status=status,
        error_type=error_type or "none",
    ).inc()
    LLM_CALL_DURATION.labels(provider=provider, status=status).observe(
        latency_ms / 1000,
    )
    if prompt_tokens is not None:
        LLM_TOKENS.labels(provider=provider, direction="prompt").inc(prompt_tokens)
    if completion_tokens is not None:
        LLM_TOKENS.labels(provider=provider, direction="completion").inc(
            completion_tokens,
        )


def set_experiment_queue_counts(counts: Mapping[str, int]) -> None:
    """Обновляет gauge очереди, включая отсутствующие в выборке статусы."""
    for status in EXPERIMENT_RUN_STATUSES:
        EXPERIMENT_QUEUE_RUNS.labels(status=status).set(counts.get(status, 0))


def set_notification_queue_counts(counts: Mapping[str, int]) -> None:
    """Обновляет gauge notification outbox по всем допустимым статусам."""
    for status in NOTIFICATION_STATUSES:
        NOTIFICATION_QUEUE_ITEMS.labels(status=status).set(counts.get(status, 0))
