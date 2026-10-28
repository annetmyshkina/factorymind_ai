from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Хранит время в UTC и возвращает timezone-aware datetime."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime должен содержать часовой пояс")

        return value.astimezone(UTC)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            # SQLite возвращает сохранённое UTC-время без tzinfo.
            return value.replace(tzinfo=UTC)

        return value.astimezone(UTC)
