"""Receiver for Telegram's Bot API webhook — the single inbound entry point for every
message sent to the shared bot, from every user.

**Validation mechanism:** Telegram's real mechanism is one static `secret_token` (set
once via `setWebhook`), echoed back on every request as
`X-Telegram-Bot-Api-Secret-Token` — compared via `hmac.compare_digest` against
`settings.TELEGRAM_WEBHOOK_SECRET`. Simpler than Calendar's per-connection
`channel_token` lookup since there's only one secret, app-wide. No auth dependency at
all otherwise — matches the Calendar webhook precedent exactly (identity comes from a DB
lookup + secret comparison, not Bearer auth). One generic error message either way (no
header vs. wrong value) — same non-leaking pattern as Calendar's webhook.

**Inbound `/start <token>` is handled as a branch here, not a separate route** — both
paths need identical prerequisites (secret validation, rate-limit check, payload
parsing), so splitting them would just duplicate that shared handling.

**`callback_query` (Feature 1.7):** a quick-pick inline-keyboard button tap, subscribed
via `allowed_updates=["message", "callback_query"]` (see `core/telegram/client.py`).
Handled as its own branch, ahead of the rate-limit/`/start` logic below, since a button
tap has nothing to do with either — it's routed straight to `process_telegram_callback`.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import UnauthorizedException
from ...core.telegram.linking import consume_link_token, link_telegram_chat
from ...core.telegram.rate_limit import is_rate_limited
from ...core.utils import queue
from ...crud.crud_telegram_link import crud_telegram_link
from ...schemas.telegram_webhook import TelegramUpdate

router = APIRouter(prefix="/webhooks/telegram", tags=["webhooks"])

INVALID_WEBHOOK_MESSAGE = "Invalid webhook secret."

EMPTY_START_MESSAGE = "Please open the Connect Telegram link in the app to get your personal linking code."
EXPIRED_TOKEN_MESSAGE = "That link has expired. Please generate a new one from the app."
LINKED_CONFIRMATION_MESSAGE = "You're linked! I'll remember our conversation here."
NOT_LINKED_MESSAGE = "Your Telegram account isn't linked yet. Open the app and use Connect Telegram to link it."


@router.post("", status_code=204)
async def telegram_webhook(
    update: TelegramUpdate,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> Response:
    expected = settings.TELEGRAM_WEBHOOK_SECRET.get_secret_value()
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(x_telegram_bot_api_secret_token, expected):
        raise UnauthorizedException(INVALID_WEBHOOK_MESSAGE)

    if update.callback_query is not None:
        callback_query = update.callback_query
        if callback_query.message is not None and callback_query.data is not None:
            link = await crud_telegram_link.get(db=db, telegram_chat_id=callback_query.message.chat.id)
            if link is not None:
                await queue.pool.enqueue_job(  # type: ignore[union-attr]
                    "process_telegram_callback",
                    str(link["user_id"]),
                    callback_query.message.chat.id,
                    callback_query.id,
                    callback_query.data,
                )
        return Response(status_code=204)

    if update.message is None or not update.message.text:
        return Response(status_code=204)  # edited_message/etc — no-op this slice

    chat_id = update.message.chat.id
    text = update.message.text.strip()
    if await is_rate_limited(chat_id):
        # Silently drop — an error status makes Telegram retry-redeliver the same
        # update, compounding a flood rather than mitigating it.
        return Response(status_code=204)

    if text.startswith("/start"):
        await _handle_start(db, chat_id, text.removeprefix("/start").strip())
        return Response(status_code=204)

    link = await crud_telegram_link.get(db=db, telegram_chat_id=chat_id)
    if link is None:
        await queue.pool.enqueue_job("send_telegram_message", chat_id, NOT_LINKED_MESSAGE)  # type: ignore[union-attr]
        return Response(status_code=204)

    await queue.pool.enqueue_job(  # type: ignore[union-attr]
        "process_telegram_message", str(link["user_id"]), chat_id, text
    )
    return Response(status_code=204)


async def _handle_start(db: AsyncSession, chat_id: int, token: str) -> None:
    """The PRD §6.4 "unlinked chat gets a prompt to link first" behavior doesn't apply
    here — this IS the linking attempt. The actual upsert/conflict-resolution logic lives
    in `core/telegram/linking.py::link_telegram_chat` (business logic belongs in `core/`,
    not the transport-layer handler that happens to trigger it)."""
    if not token:
        await queue.pool.enqueue_job("send_telegram_message", chat_id, EMPTY_START_MESSAGE)  # type: ignore[union-attr]
        return

    user_id = await consume_link_token(token)
    if user_id is None:
        await queue.pool.enqueue_job("send_telegram_message", chat_id, EXPIRED_TOKEN_MESSAGE)  # type: ignore[union-attr]
        return

    await link_telegram_chat(db, user_id, chat_id)
    await queue.pool.enqueue_job("send_telegram_message", chat_id, LINKED_CONFIRMATION_MESSAGE)  # type: ignore[union-attr]
