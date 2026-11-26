# FactoryMind AI

[![CI](https://github.com/annetmyshkina/factorymind_ai/actions/workflows/ci.yml/badge.svg)](https://github.com/annetmyshkina/factorymind_ai/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A585%25-brightgreen.svg)](#проверки)

FactoryMind AI — платформа мониторинга промышленного оборудования. Она принимает
телеметрию, выявляет отклонения, ведёт инциденты и помогает инженеру искать причины
неисправностей по технической документации и подтверждённому опыту.

## Возможности

- приём телеметрии по HTTP и MQTT;
- правила мониторинга, отклонения и автоматическое создание инцидентов;
- операторский интерфейс для работы с оборудованием и инцидентами;
- база технических документов и RAG-диагностика со ссылками на источники;
- обратная связь инженера и поиск подтверждённых решений похожих инцидентов;
- эксперименты с LLM, журнал вызовов и Evaluation Engine;
- PostgreSQL-очереди для экспериментов и Telegram-уведомлений;
- JWT-роли пользователей и отдельные API-ключи HTTP-датчиков;
- метрики Prometheus и dashboard Grafana.

## Стек

Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, Mosquitto,
Pydantic, structlog.

Frontend и эксплуатация: React, TypeScript, Vite, Prometheus, Grafana, Docker
Compose. Тесты и качество: pytest, Ruff, uv.

## Быстрый старт

Требуются Docker, Python 3.12, uv, Node.js и npm.

```bash
cp .env.example .env          # задайте POSTGRES_PASSWORD
docker compose up -d db mosquitto
uv sync --all-groups
uv run alembic upgrade head
make frontend-install
make dev
```

После запуска доступны:

- frontend: <http://127.0.0.1:5173/>;
- API: <http://127.0.0.1:8000/>;
- Swagger UI: <http://127.0.0.1:8000/docs>.

`make dev` запускает backend и frontend вместе. Для отдельных терминалов используйте
`make run` и `make frontend-dev`. PostgreSQL, Mosquitto и миграции подготавливаются
отдельно командами выше.

В development при первом старте создаётся администратор `admin` / `admin`. Эти
данные предназначены только для локальной разработки. Перед внешним развёртыванием
замените `AUTH_JWT_SECRET`, создайте рабочие учётные записи и установите
`AUTH_BOOTSTRAP_ENABLED=false`.

Production-сборка frontend создаётся командой `make frontend-build` и раздаётся
FastAPI по адресу <http://127.0.0.1:8000/ui/>.

## Аутентификация

Все доменные endpoints требуют JWT, кроме `/health` и `/metrics`. Доступ зависит
от роли:

- `viewer` — просмотр;
- `operator` — обработка инцидентов и запись HTTP-телеметрии;
- `engineer` — возможности оператора, AI-анализ, feedback, подтверждение решений
  и приём документации;
- `admin` — полный доступ и управление пользователями и конфигурацией.

Получить токен без frontend:

```bash
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8000/auth/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=admin' \
  --data-urlencode 'password=admin' | python -c \
  'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/equipment
```

HTTP-датчик может отправлять телеметрию по отдельному `X-API-Key`, привязанному к
оборудованию. Ключ выпускает администратор через
`POST /equipment/{id}/api-keys`; открытое значение возвращается только один раз.
Для ротации создайте новый ключ, переключите датчик и отзовите старый через
`POST /equipment/{id}/api-keys/{key_id}/revoke`. MQTT использует отдельную
аутентификацию брокера.

## Основные команды

```bash
make dev                  # backend и frontend
make run                  # только FastAPI
make worker               # worker экспериментов
make notification-worker  # worker Telegram-уведомлений

make db-upgrade           # применить миграции
make db-check             # текущая ревизия БД

make simulator-run        # локальный MQTT-симулятор
make simulator-start      # симулятор в Docker
make simulator-logs

make observability-start  # Prometheus и Grafana
make observability-logs
make observability-stop
```

Полный список команд: `make help`.

## Симулятор и наблюдаемость

Симулятор публикует синтетическую MQTT-телеметрию в
`factorymind/equipment/+/telemetry`. Оборудование с кодами из
`SIMULATOR_EQUIPMENT_CODES` необходимо заранее создать через API. Значения
симулятора демонстрационные и не являются нормативами производителя.

После `make observability-start` доступны:

- Prometheus: <http://127.0.0.1:9090>;
- Grafana: <http://127.0.0.1:3000>;
- dashboard `FactoryMind AI — Overview`.

Локальные данные Grafana по умолчанию — `admin` / `admin`; настройки находятся в
`.env.example`.

## Telegram-уведомления

Контур по умолчанию отключён. Для включения добавьте в `.env`:

```env
TELEGRAM_NOTIFICATIONS_ENABLED=true
TELEGRAM_BOT_TOKEN=токен_бота
TELEGRAM_CHAT_ID=идентификатор_чата
PUBLIC_APP_BASE_URL=http://адрес-приложения/ui
```

Затем примените миграции и запустите `make notification-worker`. Доставка работает
через PostgreSQL outbox с ограниченными повторными попытками; возможна повторная
отправка одного сообщения после сбоя, то есть используется семантика at-least-once.

## Проверки

```bash
make check                 # Ruff, форматирование и pytest
make coverage              # тесты с минимальным покрытием 85%
cd frontend && npm test    # компонентные тесты frontend
cd frontend && npm run build
```

CI дополнительно проверяет миграции и PostgreSQL-специфичные конкурентные сценарии.
Тесты не обращаются к реальным LLM API или MQTT-брокеру.

## Структура проекта

```text
app/             backend: API, доменные модули, workers и интеграции
frontend/        React/TypeScript интерфейс оператора
simulator/       внешний генератор синтетической MQTT-телеметрии
benchmarks/      наборы для retrieval, ответов и judge-калибровки
deploy/          Prometheus и Grafana
tests/           автоматические тесты
migrations/      миграции Alembic
docs/            спецификация и проектная документация
```

## Документация

- [Техническая спецификация](docs/spec.md) — архитектура, доменные правила,
  контракты, гарантии и этапы развития.
- [Swagger UI](http://127.0.0.1:8000/docs) — актуальные REST endpoints и схемы.
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>.
