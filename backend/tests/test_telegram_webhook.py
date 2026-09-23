"""Unit tests for the Telegram webhook receiver: secret validation, non-message no-op,
rate limiting, /start linking branch, and the linked/unlinked ordinary-message branch.
Mirrors test_calendar_webhook.py's shape."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr
from uuid6 import uuid7

from src.app.api.v1.webhooks_telegram import (
    EMPTY_START_MESSAGE,
    EXPIRED_TOKEN_MESSAGE,
    LINKED_CONFIRMATION_MESSAGE,
    NOT_LINKED_MESSAGE,
    telegram_webhook,
)
from src.app.core.exceptions.http_exceptions import UnauthorizedException
from src.app.schemas.telegram_webhook import TelegramCallbackQuery, TelegramChat, TelegramMessage, TelegramUpdate

MODULE = "src.app.api.v1.webhooks_telegram"
SECRET = "the-real-secret"


def _update(text: str | None, chat_id: int = 123) -> TelegramUpdate:
    if text is None:
        return TelegramUpdate(update_id=1, message=None)
    return TelegramUpdate(update_id=1, message=TelegramMessage(chat=TelegramChat(id=chat_id), text=text))


def _callback_update(data: str | None, chat_id: int = 123, callback_id: str = "cq-1") -> TelegramUpdate:
    message = TelegramMessage(chat=TelegramChat(id=chat_id))
    return TelegramUpdate(
        update_id=1, callback_query=TelegramCallbackQuery(id=callback_id, data=data, message=message)
    )


class TestSecretValidation:
    @pytest.mark.asyncio
    async def test_missing_header_rejected(self, mock_db):
        with patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)):
            with pytest.raises(UnauthorizedException):
                await telegram_webhook(update=_update("hi"), db=mock_db, x_telegram_bot_api_secret_token=None)

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected(self, mock_db):
        with patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)):
            with pytest.raises(UnauthorizedException):
                await telegram_webhook(update=_update("hi"), db=mock_db, x_telegram_bot_api_secret_token="wrong")


class TestNonMessageUpdate:
    @pytest.mark.asyncio
    async def test_update_without_message_is_a_no_op(self, mock_db):
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_queue.pool.enqueue_job = AsyncMock()
            response = await telegram_webhook(update=_update(None), db=mock_db, x_telegram_bot_api_secret_token=SECRET)

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_not_called()


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_rate_limited_chat_drops_silently(self, mock_db):
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.is_rate_limited", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_queue.pool.enqueue_job = AsyncMock()
            response = await telegram_webhook(
                update=_update("hello"), db=mock_db, x_telegram_bot_api_secret_token=SECRET
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_not_called()


class TestStartLinking:
    @pytest.mark.asyncio
    async def test_empty_token_enqueues_instructions(self, mock_db):
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.is_rate_limited", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_queue.pool.enqueue_job = AsyncMock()
            response = await telegram_webhook(
                update=_update("/start", chat_id=42), db=mock_db, x_telegram_bot_api_secret_token=SECRET
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_called_once_with("send_telegram_message", 42, EMPTY_START_MESSAGE)

    @pytest.mark.asyncio
    async def test_expired_token_enqueues_expired_message(self, mock_db):
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.is_rate_limited", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.consume_link_token", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_queue.pool.enqueue_job = AsyncMock()
            response = await telegram_webhook(
                update=_update("/start badtoken", chat_id=42), db=mock_db, x_telegram_bot_api_secret_token=SECRET
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_called_once_with("send_telegram_message", 42, EXPIRED_TOKEN_MESSAGE)

    @pytest.mark.asyncio
    async def test_valid_token_upserts_link_and_confirms(self, mock_db):
        """The actual upsert/conflict-resolution logic now lives in and is tested by
        core/telegram/linking.py::link_telegram_chat directly (see
        test_telegram_linking.py) — this test only proves the webhook wires a valid
        token through to that function and sends the confirmation."""
        user_id = uuid7()
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.is_rate_limited", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.consume_link_token", new=AsyncMock(return_value=user_id)),
            patch(f"{MODULE}.link_telegram_chat", new=AsyncMock()) as mock_link,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_queue.pool.enqueue_job = AsyncMock()

            response = await telegram_webhook(
                update=_update("/start goodtoken", chat_id=42), db=mock_db, x_telegram_bot_api_secret_token=SECRET
            )

        assert response.status_code == 204
        mock_link.assert_called_once_with(mock_db, user_id, 42)
        mock_queue.pool.enqueue_job.assert_called_once_with("send_telegram_message", 42, LINKED_CONFIRMATION_MESSAGE)


class TestCallbackQuery:
    @pytest.mark.asyncio
    async def test_linked_chat_enqueues_callback_processing(self, mock_db):
        user_id = uuid7()
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value={"user_id": user_id})
            mock_queue.pool.enqueue_job = AsyncMock()

            response = await telegram_webhook(
                update=_callback_update("notion_goal:abc", chat_id=99),
                db=mock_db,
                x_telegram_bot_api_secret_token=SECRET,
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_called_once_with(
            "process_telegram_callback", str(user_id), 99, "cq-1", "notion_goal:abc"
        )

    @pytest.mark.asyncio
    async def test_unlinked_chat_does_not_enqueue(self, mock_db):
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=None)
            mock_queue.pool.enqueue_job = AsyncMock()

            response = await telegram_webhook(
                update=_callback_update("notion_goal:abc", chat_id=99),
                db=mock_db,
                x_telegram_bot_api_secret_token=SECRET,
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_not_called()


class TestOrdinaryMessage:
    @pytest.mark.asyncio
    async def test_unlinked_chat_gets_not_linked_message(self, mock_db):
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.is_rate_limited", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=None)
            mock_queue.pool.enqueue_job = AsyncMock()

            response = await telegram_webhook(
                update=_update("hello there", chat_id=99), db=mock_db, x_telegram_bot_api_secret_token=SECRET
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_called_once_with("send_telegram_message", 99, NOT_LINKED_MESSAGE)

    @pytest.mark.asyncio
    async def test_linked_chat_enqueues_processing_job(self, mock_db):
        user_id = uuid7()
        with (
            patch(f"{MODULE}.settings.TELEGRAM_WEBHOOK_SECRET", SecretStr(SECRET)),
            patch(f"{MODULE}.is_rate_limited", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value={"user_id": user_id})
            mock_queue.pool.enqueue_job = AsyncMock()

            response = await telegram_webhook(
                update=_update("hello there", chat_id=99), db=mock_db, x_telegram_bot_api_secret_token=SECRET
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_called_once_with("process_telegram_message", str(user_id), 99, "hello there")
