"""Вспомогательные функции провайдеров."""

import time


def elapsed_ms(started: float) -> int:
    """Возвращает прошедшее время в миллисекундах."""
    return int((time.perf_counter() - started) * 1000)


def optional_int(value: object) -> int | None:
    """Возвращает int, если значение действительно целое число."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
