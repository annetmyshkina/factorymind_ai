"""Минимальный клиент Telegram Bot API для исходящих сообщений."""

import httpx2

from app.notifications.errors import TelegramDeliveryError


class TelegramClient:
    """Отправляет plain-text сообщения в один настроенный Telegram-чат."""

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        base_url: str = "https://api.telegram.org",
        timeout: float = 10.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = httpx2.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
        )

    def send_message(self, text: str) -> str:
        """Отправляет сообщение и возвращает Telegram message_id."""
        try:
            response = self._client.post(
                f"/bot{self._bot_token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
        except httpx2.TimeoutException as exc:
            raise TelegramDeliveryError(
                "Telegram не ответил за отведённое время",
                retryable=True,
            ) from exc
        except httpx2.HTTPError as exc:
            raise TelegramDeliveryError(
                "Не удалось подключиться к Telegram API",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            retryable = (
                response.status_code in {408, 429} or response.status_code >= 500
            )
            raise TelegramDeliveryError(
                f"Telegram API вернул HTTP {response.status_code}",
                retryable=retryable,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramDeliveryError(
                "Telegram API вернул некорректный JSON",
                retryable=True,
            ) from exc

        if not isinstance(data, dict) or data.get("ok") is not True:
            error_code = data.get("error_code") if isinstance(data, dict) else None
            retryable = error_code in {408, 429} or (
                isinstance(error_code, int) and error_code >= 500
            )
            raise TelegramDeliveryError(
                "Telegram API отклонил сообщение",
                retryable=retryable,
            )

        result = data.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if isinstance(message_id, bool) or not isinstance(message_id, int):
            raise TelegramDeliveryError(
                "Telegram API не вернул message_id",
                retryable=True,
            )
        return str(message_id)

    def close(self) -> None:
        self._client.close()
