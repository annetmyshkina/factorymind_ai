import json

import httpx2
import pytest

from app.notifications.errors import TelegramDeliveryError
from app.notifications.telegram import TelegramClient


def _mock(handler) -> httpx2.MockTransport:
    return httpx2.MockTransport(handler)


def test_telegram_client_sends_plain_text_message() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, json={"ok": True, "result": {"message_id": 42}})

    client = TelegramClient(
        bot_token="test-token",
        chat_id="-100123",
        base_url="https://telegram.test",
        transport=_mock(handler),
    )
    try:
        message_id = client.send_message("Инцидент #7")
    finally:
        client.close()

    assert message_id == "42"
    assert str(captured[0].url) == ("https://telegram.test/bottest-token/sendMessage")
    assert json.loads(captured[0].content) == {
        "chat_id": "-100123",
        "text": "Инцидент #7",
        "disable_web_page_preview": True,
    }


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(401, False), (400, False), (408, True), (429, True), (500, True)],
)
def test_telegram_client_classifies_http_errors(
    status_code: int,
    retryable: bool,
) -> None:
    client = TelegramClient(
        bot_token="secret-token",
        chat_id="1",
        transport=_mock(lambda request: httpx2.Response(status_code)),
    )
    try:
        with pytest.raises(TelegramDeliveryError) as exc_info:
            client.send_message("test")
    finally:
        client.close()

    assert exc_info.value.retryable is retryable
    assert "secret-token" not in str(exc_info.value)


def test_telegram_client_hides_token_on_network_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("request with secret-token failed")

    client = TelegramClient(
        bot_token="secret-token",
        chat_id="1",
        transport=_mock(handler),
    )
    try:
        with pytest.raises(TelegramDeliveryError) as exc_info:
            client.send_message("test")
    finally:
        client.close()

    assert exc_info.value.retryable
    assert "secret-token" not in str(exc_info.value)


def test_telegram_client_rejects_missing_message_id() -> None:
    client = TelegramClient(
        bot_token="token",
        chat_id="1",
        transport=_mock(
            lambda request: httpx2.Response(200, json={"ok": True, "result": {}}),
        ),
    )
    try:
        with pytest.raises(TelegramDeliveryError, match="message_id") as exc_info:
            client.send_message("test")
    finally:
        client.close()

    assert exc_info.value.retryable
