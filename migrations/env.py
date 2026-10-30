from logging.config import fileConfig

from alembic import context

from app.core.database import Base, engine
from app.equipment import models as equipment_models  # noqa: F401
from app.incidents import models as incidents_models  # noqa: F401
from app.monitoring.models import EquipmentDeviation, MonitoringRule  # noqa: F401
from app.telemetry import models as telemetry_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_section_option(
    config.config_ini_section,
    "sqlalchemy.url",
    engine.url.render_as_string(hide_password=False).replace("%", "%%"),
)


def run_migrations_offline() -> None:
    """Запускает миграции без обычного подключения к БД."""

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Запускает миграции с подключением к БД."""

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
