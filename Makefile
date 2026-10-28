.DEFAULT_GOAL := help

# Команды приложения
.PHONY: help install run lint format check lint-fix logs

# Команды работы с базой данных
.PHONY: db-init db-check db-revision db-history db-upgrade db-shell db-start

help:
	@echo "FactoryMind AI — команды разработки"
	@echo ""
	@echo "Общие команды:"
	@echo "  make install             - установить зависимости"
	@echo "  make run                 - запустить FastAPI"
	@echo "  make lint                - проверить код"
	@echo "  make format              - отформатировать код"
	@echo "  make check               - выполнить все проверки"
	@echo ""
	@echo "Работа с базой данных:"
	@echo "  make db-init             - инициализировать Alembic"
	@echo "  make db-check            - проверить подключение и ревизию"
	@echo "  make db-revision message=\"описание\" - создать миграцию"
	@echo "  make db-history          - показать историю миграций"
	@echo "  make db-upgrade          - применить миграции"
	@echo ""
	@echo "Справка:"
	@echo "  make help                - показать список команд"

install:
	uv sync --all-groups

run:
	uv run uvicorn app.main:app --reload

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

check: lint
	uv run ruff format --check .
	uv run pytest

db-init:
	uv run alembic init migrations

db-check:
	uv run alembic current

db-revision:
	uv run alembic revision --autogenerate -m "$(message)"

db-history:
	uv run alembic history

db-upgrade:
	uv run alembic upgrade head

db-shell:
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

db-start:
	docker compose up -d db

logs:
	@for file in logs/app.log logs/errors.log; do \
		if [ -f "$$file" ]; then \
			echo "===== $$file ====="; \
			tail -n 20 "$$file"; \
		else \
			echo "Файл $$file пока не создан: $$file"; \
		fi; \
	done