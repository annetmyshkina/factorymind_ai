"""Общие ошибки детерминированных benchmark-suite."""


class BenchmarkError(ValueError):
    """Benchmark некорректен или не соответствует подготовленному корпусу."""
