"""Unit tests for core/telegram/client.py: request shape for send_message/set_webhook,
and the inline-keyboard builder. Telegram's endpoints are mocked via httpx.AsyncClient
patches, same convention as test_google_calendar_integration.py."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.app.core.telegram.client import build_inline_keyboard, telegram_send_message, telegram_set_webhook


def make_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, json=json_body or {}, request=httpx.Request("POST", "https://example.com")
    )


class TestBuildInlineKeyboard:
    def test_builds_rows_of_buttons(self):
        keyboard = build_inline_keyboard([[("Yes", "yes"), ("No", "no")], [("Cancel", "cancel")]])

        assert keyboard == {
            "inline_keyboard": [
                [{"text": "Yes", "callback_data": "yes"}, {"text": "No", "callback_data": "no"}],
                [{"text": "Cancel", "callback_data": "cancel"}],
            ]
        }


class TestTelegramSendMessage:
    @pytest.mark.asyncio
    async def test_sends_chat_id_and_text(self):
        mock_post = AsyncMock(return_value=make_response(200, {"ok": True}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            await telegram_send_message(42, "hello")

        body = mock_post.call_args.kwargs["json"]
        assert body == {"chat_id": 42, "text": "hello"}

    @pytest.mark.asyncio
    async def test_includes_reply_markup_when_given(self):
        mock_post = AsyncMock(return_value=make_response(200, {"ok": True}))
        markup = build_inline_keyboard([[("Yes", "yes")]])
        with patch.object(httpx.AsyncClient, "post", mock_post):
            await telegram_send_message(42, "hello", reply_markup=markup)

        body = mock_post.call_args.kwargs["json"]
        assert body["reply_markup"] == markup

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        mock_post = AsyncMock(return_value=make_response(400, {"ok": False}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await telegram_send_message(42, "hello")


class TestTelegramSetWebhook:
    @pytest.mark.asyncio
    async def test_sends_url_and_secret_token(self):
        mock_post = AsyncMock(return_value=make_response(200, {"ok": True}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            await telegram_set_webhook("https://example.com/webhook", "secret-token")

        body = mock_post.call_args.kwargs["json"]
        assert body == {
            "url": "https://example.com/webhook",
            "secret_token": "secret-token",
            "allowed_updates": ["message"],
        }
