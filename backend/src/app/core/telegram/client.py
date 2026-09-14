"""Telegram Bot API calls — plain `httpx`, same retry pattern as google_calendar.py."""

from typing import Any

import httpx

from ..config import settings
from ..utils.http_retry import execute_with_retry

TELEGRAM_API_BASE = "https://api.telegram.org"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503})


def _api_url(method: str) -> str:
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
    return f"{TELEGRAM_API_BASE}/bot{token}/{method}"


def build_inline_keyboard(buttons: list[list[tuple[str, str]]]) -> dict[str, Any]:
    """Generic inline-keyboard primitive — no live consumer this slice. Each
    `(text, callback_data)` pair becomes one button; each inner list is one row."""
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": callback_data} for text, callback_data in row] for row in buttons
        ]
    }


async def telegram_send_message(chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.post(_api_url("sendMessage"), json=payload, timeout=30.0)

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()


async def telegram_set_webhook(webhook_url: str, secret_token: str) -> None:
    """`allowed_updates=["message"]` — deliberate, no `callback_query`/`edited_message`
    subscription yet. Called once per environment via `scripts/set_telegram_webhook.py`,
    never on the request/job path."""
    payload = {"url": webhook_url, "secret_token": secret_token, "allowed_updates": ["message"]}

    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.post(_api_url("setWebhook"), json=payload, timeout=30.0)

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()
