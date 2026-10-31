# FactoryMind AI

[![CI](https://github.com/annetmyshkina/factorymind_ai/actions/workflows/ci.yml/badge.svg)](https://github.com/annetmyshkina/factorymind_ai/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A585%25-brightgreen.svg)](#проверки)

Платформа мониторинга промышленного оборудования: приём телеметрии по HTTP и MQTT,
правила мониторинга и отклонения, инциденты с конечным автоматом статусов и аудитом
событий.

## Стек

FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, Mosquitto (paho-mqtt), structlog,
pytest, ruff, uv.

## Быстрый старт

```bash
cp .env.example .env          # задайте POSTGRES_PASSWORD
docker compose up -d db mosquitto
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Swagger UI: <http://127.0.0.1:8000/docs>.

Тесты не требуют PostgreSQL и MQTT: они работают на in-memory SQLite
(`tests/conftest.py`), MQTT-подписчик при `ENVIRONMENT=test` не запускается.

## Проверки

```bash
make check        # ruff check + ruff format --check + pytest
make coverage     # pytest с покрытием (порог 85%)
```

CI (`.github/workflows/ci.yml`) на каждый push в `main` и pull request прогоняет
линтер, проверку форматирования и тесты с покрытием.

## API

| Метод | Путь | Назначение |
| --- | --- | --- |
| `GET` | `/health` | Проверка живости |
| `POST` | `/equipment` | Создать оборудование |
| `GET` | `/equipment` | Список оборудования |
| `GET` | `/equipment/{id}` | Карточка оборудования |
| `PATCH` | `/equipment/{id}` | Обновить оборудование |
| `POST` | `/equipment/{id}/telemetry` | Добавить показания (запускает правила) |
| `GET` | `/equipment/{id}/telemetry` | История показаний (`limit`, `offset`, `since`, `until`) |
| `POST` | `/equipment/{id}/monitoring-rules` | Создать правило мониторинга |
| `GET` | `/equipment/{id}/monitoring-rules` | Правила оборудования |
| `GET` | `/equipment/{id}/deviations` | Зафиксированные отклонения |
| `POST` | `/incidents` | Создать инцидент |
| `GET` | `/incidents` | Список инцидентов (`status`, `equipment_id`) |
| `GET` | `/incidents/{id}` | Инцидент с отклонениями и историей |
| `PATCH` | `/incidents/{id}` | Статус, severity, исполнитель, описание |
| `POST` | `/incidents/{id}/deviations` | Привязать отклонение (идемпотентно) |
| `GET` | `/incidents/{id}/events` | История событий инцидента |

Статусы инцидента: `open → in_progress → resolved → closed`, допускается
`open ↔ closed`, `in_progress → open`, `resolved → in_progress`. Недопустимый
переход возвращает `409`.

### Автосоздание инцидентов

Отклонение, зафиксированное правилом мониторинга, автоматически создаёт инцидент —
и для телеметрии по HTTP, и для MQTT:

- severity: `temperature_c` → `critical`, `vibration_mm_s` → `high`, остальные
  метрики → `medium`;
- если по оборудованию уже есть инцидент в статусе `open` или `in_progress`,
  новое отклонение привязывается к нему, второй инцидент не создаётся;
- `resolved` и `closed` инциденты не блокируют создание нового;
- телеметрия, отклонения, инцидент и события аудита сохраняются одной транзакцией.

## MQTT

Топик: `factorymind/equipment/+/telemetry`, где `+` — код оборудования.

```json
{
  "event_id": "6f1c0f1e-2a5e-4d3b-9a1c-1f2e3d4c5b6a",
  "equipment_code": "COOLER-01",
  "measured_at": "2026-10-31T09:00:00Z",
  "temperature_c": 82.4,
  "vibration_mm_s": 4.1,
  "compressor_running": true
}
```

`event_id` используется для идемпотентности (таблица `processed_mqtt_events`).
Остальные поля соответствуют `TelemetryCreate`: `ambient_temperature_c`,
`suction_pressure_kpa_g`, `discharge_pressure_kpa_g`, `compressor_current_a`,
`compressor_vsd_frequency_hz`, `coolant_flow_rate_m3_h`.

## Структура

```text
app/
  api/           сборка роутеров, health
  core/          конфиг, БД, логирование, middleware
  equipment/     оборудование
  telemetry/     показания, MQTT-подписчик и обработчик
  monitoring/    правила мониторинга и отклонения
  incidents/     инциденты: модели, сервис, API
tests/           pytest, SQLite in-memory
migrations/      Alembic
docs/            документация
```
