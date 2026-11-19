# FactoryMind AI

[![CI](https://github.com/annetmyshkina/factorymind_ai/actions/workflows/ci.yml/badge.svg)](https://github.com/annetmyshkina/factorymind_ai/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A585%25-brightgreen.svg)](#проверки)

Платформа мониторинга промышленного оборудования: приём телеметрии по HTTP и MQTT,
правила мониторинга и отклонения, инциденты с конечным автоматом статусов и аудитом
событий.

## Стек

FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, Mosquitto (paho-mqtt), React,
TypeScript, Vite, structlog, Prometheus, Grafana, pytest, ruff, uv.

## Быстрый старт

```bash
cp .env.example .env          # задайте POSTGRES_PASSWORD
docker compose up -d db mosquitto
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Swagger UI: <http://127.0.0.1:8000/docs>.

Для совместного запуска backend и frontend в режиме разработки (вместо отдельного
запуска uvicorn выше):

```bash
make frontend-install       # один раз, затем при обновлении зависимостей
make dev
```

Откройте <http://127.0.0.1:5173/>. Vite проксирует API-запросы в FastAPI на
`127.0.0.1:8000`; изменения исходников подхватываются автоматически. `Ctrl+C`
останавливает оба сервера, завершение одного сервера также останавливает второй.
Команда требует Bash и `setsid` (Linux/WSL); PostgreSQL и Mosquitto должны быть
запущены отдельно через `docker compose up -d db mosquitto`, миграции применены.
При необходимости серверы можно запускать отдельно: `make run` и
`make frontend-dev` в двух терминалах.

После `make frontend-build` FastAPI раздаёт собранный интерфейс по адресу
<http://127.0.0.1:8000/ui/>. Если API недоступен, интерфейс явно переходит в
демонстрационный режим; адрес внешнего API можно указать в настройках. Нажатие на
инцидент открывает рабочую карточку: в ней доступны назначение исполнителя, переходы
статуса, связанные отклонения и история, RAG-анализ, feedback и подтверждение
фактического результата. В демонстрационном режиме изменяющие действия отключены.
Текущий раздел, фильтр списка и открытый инцидент сохраняются в hash-части URL
(например, `/ui/#incidents?filter=all&incident=28`) и восстанавливаются после
перезагрузки страницы.

Тесты не требуют PostgreSQL и MQTT: они работают на in-memory SQLite
(`tests/conftest.py`), MQTT-подписчик при `ENVIRONMENT=test` не запускается.

## Проверки

```bash
make check        # ruff check + ruff format --check + pytest
make coverage     # pytest с покрытием (порог 85%)
cd frontend && npm test  # компонентные тесты навигации и сохранения инцидента
```

Офлайн RAG benchmark запускается на подготовленном PostgreSQL-корпусе без записи
результатов в БД:

```bash
uv run python -m app.evaluation.cli benchmarks/rag/retrieval-v1.json
uv run python -m app.evaluation.answer_cli benchmarks/rag/answers-v1.json
```

CI (`.github/workflows/ci.yml`) на каждый push в `main` и pull request прогоняет
линтер, проверку форматирования и тесты с покрытием. Отдельная job применяет
миграции к PostgreSQL, проверяет отсутствие расхождений схемы (`alembic check`)
и обратимость миграций (`downgrade base` → `upgrade head`).

## Наблюдаемость

API публикует Prometheus-метрики на <http://127.0.0.1:8000/metrics>. Отдельный
experiment worker публикует свои метрики на `127.0.0.1:9101`; сервер метрик
запускается вместе с `make worker`.

Для полного локального контура запустите процессы в отдельных терминалах:

```bash
make run
make worker
make observability-start
```

После запуска доступны:

- Prometheus: <http://127.0.0.1:9090>;
- Grafana: <http://127.0.0.1:3000>;
- готовый dashboard `FactoryMind AI — Overview` в папке `FactoryMind AI`.

Локальные логин и пароль Grafana по умолчанию — `admin`/`admin`; их можно изменить
через `GRAFANA_ADMIN_USER` и `GRAFANA_ADMIN_PASSWORD`. Профиль использует host
network, чтобы контейнер Prometheus мог собирать метрики процессов, запущенных на
Linux-хосте. Метрики включают HTTP rate/latency/errors, результаты обработки MQTT,
создание инцидентов, LLM-вызовы и токены, очередь экспериментов, retry, lease
recovery и состояние worker-а. Значения идентификаторов оборудования, инцидентов и
непараметризованные URL не используются как labels.

Остановка и просмотр логов:

```bash
make observability-logs
make observability-stop
```

## API

| Метод | Путь | Назначение |
| --- | --- | --- |
| `GET` | `/health` | Проверка живости |
| `GET` | `/metrics` | Метрики API в формате Prometheus |
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
| `POST` | `/incidents/{id}/analyses` | Выполнить RAG-анализ с проверяемыми источниками |
| `GET` | `/incidents/{id}/analyses` | Получить историю версий анализа |
| `GET` | `/incidents/{id}/similar-resolutions` | Найти похожий подтверждённый опыт |
| `POST` | `/incidents/{id}/analyses/{analysis_id}/feedback` | Оценить анализ |
| `GET` | `/incidents/{id}/analyses/{analysis_id}/feedback` | История оценок анализа |
| `POST` | `/incidents/{id}/resolution` | Подтвердить результат диагностики |
| `GET` | `/incidents/{id}/resolution` | Текущий результат диагностики |
| `PATCH` | `/incidents/{id}/resolution` | Исправить подтверждённый результат |
| `POST` | `/incidents/{id}/resolution/revoke` | Отозвать подтверждение |
| `GET` | `/incidents/{id}/resolution/events` | Аудит изменений результата |
| `POST` | `/ai/calls` | Вызвать модель и сохранить вызов |
| `GET` | `/ai/calls` | Журнал (`provider`, `status`, `limit`, `offset`) |
| `GET` | `/ai/calls/{id}` | Карточка вызова |
| `POST` | `/ai/prompts` | Создать неизменяемую версию промпта |
| `GET` | `/ai/prompts` | Версии промптов (`name`, `limit`, `offset`) |
| `GET` | `/ai/prompts/{id}` | Карточка версии промпта |
| `POST` | `/experiments` | Создать эксперимент со списком прогонов |
| `GET` | `/experiments/{id}` | Статусы, ответы и оценки прогонов |
| `GET` | `/experiments/{id}/report` | Сравнительный отчёт |
| `GET` | `/evaluations/operational/incident-analyses` | Эксплуатационные сигналы AI-анализов |
| `POST` | `/knowledge/documents` | Создать карточку технического документа |
| `GET` | `/knowledge/documents` | Каталог и фильтр применимости к оборудованию |
| `GET` | `/knowledge/documents/{id}` | Версии и области применения документа |
| `POST` | `/knowledge/documents/{id}/versions` | Загрузить PDF, TXT или Markdown до 10 МБ |
| `GET` | `/knowledge/versions/{id}/download` | Скачать исходный файл |
| `POST` | `/knowledge/versions/{id}/applicability` | Связать версию с оборудованием или типом |
| `POST` | `/knowledge/versions/{id}/process` | Извлечь текст и сохранить воспроизводимые чанки |
| `DELETE` | `/knowledge/applicability/{id}` | Удалить ошибочную связь применимости |
| `GET` | `/knowledge/search` | Найти применимые фрагменты (`q`, `equipment_id`) |

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

### Симулятор телеметрии

Отдельный процесс `simulator` имитирует внешнее оборудование и публикует тот же
MQTT-контракт. Он не обращается к БД и не импортирует доменные сервисы. Перед
запуском создайте в FactoryMind оборудование с кодами из
`SIMULATOR_EQUIPMENT_CODES`; сообщения для неизвестных кодов будут штатно
отклонены подписчиком.

```bash
make mqtt-start
make simulator-run
```

Для контейнерного запуска:

```bash
make simulator-start
make simulator-logs
```

Доступны отдельные сценарии `normal`, `warning`, `critical`, `recovery` и цикл
`demo_cycle`. Значения являются синтетическими демонстрационными данными, а не
нормативами производителя. Интервал, seed и конечное число шагов настраиваются
через env; `SIMULATOR_STEPS=0` означает работу до остановки. Параметры
`SIMULATOR_DROP_RATE`, `SIMULATOR_DUPLICATE_RATE`, `SIMULATOR_DELAY_RATE` и
`SIMULATOR_DELAY_STEPS` позволяют воспроизводить потери, повторную доставку и
задержанные сообщения. Каждый процесс получает отдельный MQTT client ID, поэтому
локальный и контейнерный симуляторы могут работать одновременно.

## Структура

```text
app/
  api/           сборка роутеров, health
  core/          конфиг, БД, логирование, middleware
  equipment/     оборудование
  telemetry/     показания, MQTT-подписчик и обработчик
  monitoring/    правила мониторинга и отклонения
  incidents/     инциденты, AI-анализ, feedback и подтверждённые результаты
  ai/            AI Gateway: контракты и провайдеры LLM
  experiments/   запуск экспериментов, оценки и отчёты
  knowledge/     документы, обработка, применимость и retrieval
  observability/ Prometheus-метрики и технический endpoint
frontend/        React/TypeScript интерфейс оператора
deploy/          конфигурация Prometheus и provisioning Grafana
simulator/       внешний генератор синтетической MQTT-телеметрии
tests/           pytest, SQLite in-memory
migrations/      Alembic
docs/            документация
```

## Документация

- [Спецификация проекта](docs/spec.md) — требования, домен, архитектура,
  AI-подсистема, критерии оценки и этапы развития.
- OpenAPI генерируется FastAPI: `/openapi.json`, интерактивная версия — `/docs`.
