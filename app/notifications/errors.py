"""Ошибки доставки внешних уведомлений."""


class TelegramDeliveryError(Exception):
    """Безопасная для журнала ошибка Telegram без токена и URL запроса."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable
