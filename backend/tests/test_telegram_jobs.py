"""Unit tests for core/telegram/jobs.py's ARQ job functions:
`process_telegram_message` (both ConversationMessage rows created with correct
role/channel, extraction called with the right source_type/source_channel, an extraction
failure doesn't block the reply) and `send_telegram_message` (failure increments/sets the
health columns and retries; success resets them)."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from arq import Retry
from uuid6 import uuid7

from src.app.core.telegram import jobs

MODULE = "src.app.core.telegram.jobs"


class _FakeSessionCM:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc_info):
        return False


def fake_local_session(db):
    return lambda: _FakeSessionCM(db)


def _mock_cache_lock_available():
    """A mock `cache` module whose lock is always free — `.set(..., nx=True, ...)`
    returns truthy (lock acquired), matching real redis.asyncio's SET NX behavior."""
    mock_cache = AsyncMock()
    mock_cache.client.set = AsyncMock(return_value=True)
    mock_cache.client.delete = AsyncMock()
    return mock_cache


class TestProcessTelegramMessage:
    @pytest.mark.asyncio
    async def test_stores_user_and_assistant_turns_and_sends_reply(self, mock_db):
        user_id = uuid7()
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.cache", new=_mock_cache_lock_available()) as mock_cache,
            patch(f"{MODULE}.get_oldest_pending_clarification", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.crud_conversation_messages") as mock_crud,
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_extract,
            patch(f"{MODULE}.generate_conversation_reply", new=AsyncMock(return_value="a reply")) as mock_reply,
        ):
            mock_crud.create = AsyncMock()
            ctx = {"redis": AsyncMock()}

            await jobs.process_telegram_message(ctx, str(user_id), 42, "hello there")

        mock_cache.client.set.assert_called_once_with("telegram_processing_lock:42", "1", nx=True, ex=30)
        mock_cache.client.delete.assert_called_once_with("telegram_processing_lock:42")

        assert mock_crud.create.call_count == 2
        first_call_object = mock_crud.create.call_args_list[0].kwargs["object"]
        assert first_call_object.role == "user"
        assert first_call_object.channel == "telegram"
        assert first_call_object.content == "hello there"

        second_call_object = mock_crud.create.call_args_list[1].kwargs["object"]
        assert second_call_object.role == "assistant"
        assert second_call_object.channel == "telegram"
        assert second_call_object.content == "a reply"

        mock_extract.assert_called_once_with(
            db=mock_db,
            user_id=user_id,
            source_type="conversation",
            source_channel="telegram",
            content="hello there",
            embed=True,
        )
        mock_reply.assert_called_once_with(mock_db, user_id)
        ctx["redis"].enqueue_job.assert_called_once_with("send_telegram_message", 42, "a reply")

    @pytest.mark.asyncio
    async def test_extraction_failure_does_not_block_reply(self, mock_db):
        user_id = uuid7()
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.cache", new=_mock_cache_lock_available()),
            patch(f"{MODULE}.get_oldest_pending_clarification", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.crud_conversation_messages") as mock_crud,
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock(side_effect=Exception("boom"))),
            patch(f"{MODULE}.generate_conversation_reply", new=AsyncMock(return_value="a reply")) as mock_reply,
        ):
            mock_crud.create = AsyncMock()
            ctx = {"redis": AsyncMock()}

            await jobs.process_telegram_message(ctx, str(user_id), 42, "hello there")

        mock_reply.assert_called_once()
        ctx["redis"].enqueue_job.assert_called_once_with("send_telegram_message", 42, "a reply")

    @pytest.mark.asyncio
    async def test_lock_contention_defers_without_touching_db(self, mock_db):
        """When another worker already holds this chat's lock, the job must raise Retry
        immediately, before any DB write — proves the fix for the concurrent-processing
        race (two messages from the same chat racing on conversation history)."""
        mock_cache = AsyncMock()
        mock_cache.client.set = AsyncMock(return_value=False)  # lock NOT acquired
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.cache", new=mock_cache),
            patch(f"{MODULE}.crud_conversation_messages") as mock_crud,
        ):
            mock_crud.create = AsyncMock()
            with pytest.raises(Retry):
                await jobs.process_telegram_message({"redis": AsyncMock()}, str(uuid7()), 42, "hello there")

        mock_crud.create.assert_not_called()
        mock_cache.client.delete.assert_not_called()  # never acquired, so nothing to release


class TestSendTelegramMessage:
    @pytest.mark.asyncio
    async def test_success_resets_failure_columns(self, mock_db):
        link = {"id": uuid7(), "consecutive_failure_count": 3}
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.telegram_send_message", new=AsyncMock()),
        ):
            mock_crud.get = AsyncMock(return_value=link)
            mock_crud.update = AsyncMock()

            await jobs.send_telegram_message({"job_try": 1}, 42, "hi")

        mock_crud.update.assert_called_once_with(
            db=mock_db, object={"consecutive_failure_count": 0, "last_failure_at": None}, id=link["id"]
        )

    @pytest.mark.asyncio
    async def test_success_with_no_prior_failures_skips_update(self, mock_db):
        link = {"id": uuid7(), "consecutive_failure_count": 0}
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.telegram_send_message", new=AsyncMock()),
        ):
            mock_crud.get = AsyncMock(return_value=link)
            mock_crud.update = AsyncMock()

            await jobs.send_telegram_message({"job_try": 1}, 42, "hi")

        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_increments_count_and_retries(self, mock_db):
        link = {"id": uuid7(), "consecutive_failure_count": 1}
        request = httpx.Request("POST", "https://example.com")
        http_error = httpx.HTTPStatusError("boom", request=request, response=httpx.Response(500, request=request))
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.telegram_send_message", new=AsyncMock(side_effect=http_error)),
        ):
            mock_crud.get = AsyncMock(return_value=link)
            mock_crud.update = AsyncMock()

            with pytest.raises(Retry):
                await jobs.send_telegram_message({"job_try": 1}, 42, "hi")

        update_kwargs = mock_crud.update.call_args.kwargs
        assert update_kwargs["object"]["consecutive_failure_count"] == 2
        assert isinstance(update_kwargs["object"]["last_failure_at"], datetime)

    @pytest.mark.asyncio
    async def test_transport_error_increments_count_and_retries(self, mock_db):
        """httpx.ConnectError (a network-level failure with no HTTP response at all) must
        be caught the same way as httpx.HTTPStatusError — proves the fix for the earlier
        bug where only HTTPStatusError was caught, so a transport failure propagated
        uncaught and ARQ silently never retried it despite max_tries=5."""
        link = {"id": uuid7(), "consecutive_failure_count": 1}
        transport_error = httpx.ConnectError("connection refused")
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.telegram_send_message", new=AsyncMock(side_effect=transport_error)),
        ):
            mock_crud.get = AsyncMock(return_value=link)
            mock_crud.update = AsyncMock()

            with pytest.raises(Retry):
                await jobs.send_telegram_message({"job_try": 1}, 42, "hi")

        update_kwargs = mock_crud.update.call_args.kwargs
        assert update_kwargs["object"]["consecutive_failure_count"] == 2
        assert isinstance(update_kwargs["object"]["last_failure_at"], datetime)

    @pytest.mark.asyncio
    async def test_unlinked_chat_still_attempts_send(self, mock_db):
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_telegram_link") as mock_crud,
            patch(f"{MODULE}.telegram_send_message", new=AsyncMock()) as mock_send,
        ):
            mock_crud.get = AsyncMock(return_value=None)
            mock_crud.update = AsyncMock()

            await jobs.send_telegram_message({"job_try": 1}, 42, "hi")

        mock_send.assert_called_once_with(42, "hi", None)
        mock_crud.update.assert_not_called()
