"""Unit tests for the narrow, Notion-specific clarification escalation
(core/notion/clarification.py): Telegram-linked vs. not-linked branches, and the
`process_telegram_message`/`process_telegram_callback` pending-clarification routing."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

CLARIFICATION_MODULE = "src.app.core.notion.clarification"
TELEGRAM_JOBS_MODULE = "src.app.core.telegram.jobs"


class TestEscalateInsufficientContext:
    @pytest.mark.asyncio
    async def test_no_telegram_link_only_persists_the_flag(self, mock_db):
        from src.app.core.notion.clarification import escalate_insufficient_context

        with (
            patch(f"{CLARIFICATION_MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{CLARIFICATION_MODULE}.crud_telegram_link") as mock_link,
        ):
            mock_sync.update = AsyncMock()
            mock_link.get = AsyncMock(return_value=None)
            mock_redis = AsyncMock()

            await escalate_insufficient_context(mock_db, mock_redis, uuid7(), uuid7(), "some block summary")

        mock_sync.update.assert_called_once()
        mock_redis.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_linked_sends_a_question_with_quick_pick_goals(self, mock_db):
        from src.app.core.notion.clarification import escalate_insufficient_context

        goals = [{"id": uuid7(), "title": "Ship the redesign"}]
        with (
            patch(f"{CLARIFICATION_MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{CLARIFICATION_MODULE}.crud_telegram_link") as mock_link,
            patch(f"{CLARIFICATION_MODULE}.crud_goals") as mock_goals,
        ):
            mock_sync.update = AsyncMock()
            mock_link.get = AsyncMock(return_value={"telegram_chat_id": 42})
            mock_goals.get_multi = AsyncMock(return_value={"data": goals})
            mock_redis = AsyncMock()

            await escalate_insufficient_context(mock_db, mock_redis, uuid7(), uuid7(), "some block summary")

        mock_redis.enqueue_job.assert_called_once()
        args = mock_redis.enqueue_job.call_args.args
        assert args[0] == "send_telegram_message"
        assert args[1] == 42


class TestPendingClarificationRouting:
    @pytest.mark.asyncio
    async def test_free_text_reply_routes_to_clarification_not_generic_conversation(self, mock_db):
        """A free-text reply to an outstanding clarification skips the generic
        extraction+conversation-reply path entirely."""
        from src.app.core.telegram.jobs import process_telegram_message

        pending = {"id": uuid7(), "user_id": uuid7(), "notion_block_id": "block-1", "notion_page_id": "page-1"}
        with (
            patch(f"{TELEGRAM_JOBS_MODULE}.cache") as mock_cache,
            patch(f"{TELEGRAM_JOBS_MODULE}.local_session") as mock_session_factory,
            patch(f"{TELEGRAM_JOBS_MODULE}.get_oldest_pending_clarification", new=AsyncMock(return_value=pending)),
            patch(f"{TELEGRAM_JOBS_MODULE}._resolve_pending_clarification", new=AsyncMock()) as mock_resolve,
            patch(f"{TELEGRAM_JOBS_MODULE}.crud_conversation_messages") as mock_conv,
            patch(f"{TELEGRAM_JOBS_MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_extract,
        ):
            mock_cache.client = AsyncMock()
            mock_cache.client.set = AsyncMock(return_value=True)
            mock_cache.client.delete = AsyncMock()
            mock_session_factory.return_value.__aenter__.return_value = mock_db
            ctx = {"redis": AsyncMock()}

            await process_telegram_message(ctx, str(pending["user_id"]), 42, "It's the redesign goal")

        mock_resolve.assert_called_once()
        mock_conv.create.assert_not_called()
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_query_tap_resolves_matched_goal(self):
        from src.app.core.telegram.jobs import process_telegram_callback

        pending = {"id": uuid7(), "user_id": uuid7(), "notion_block_id": "block-1", "notion_page_id": "page-1"}
        goal_id = uuid7()
        with (
            patch(f"{TELEGRAM_JOBS_MODULE}.telegram_answer_callback_query", new=AsyncMock()) as mock_answer,
            patch(f"{TELEGRAM_JOBS_MODULE}.local_session") as mock_session_factory,
            patch(f"{TELEGRAM_JOBS_MODULE}.get_oldest_pending_clarification", new=AsyncMock(return_value=pending)),
            patch(f"{TELEGRAM_JOBS_MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
            patch(f"{TELEGRAM_JOBS_MODULE}.crud_notion_block_sync") as mock_sync,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_sync.update = AsyncMock()
            ctx = {"redis": AsyncMock()}

            await process_telegram_callback(ctx, str(pending["user_id"]), 42, "cq-1", f"notion_goal:{goal_id}")

        mock_answer.assert_called_once_with("cq-1")
        mock_persist.assert_called_once()
        mock_sync.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_callback_data_prefix_is_a_no_op(self):
        from src.app.core.telegram.jobs import process_telegram_callback

        with (
            patch(f"{TELEGRAM_JOBS_MODULE}.telegram_answer_callback_query", new=AsyncMock()) as mock_answer,
            patch(f"{TELEGRAM_JOBS_MODULE}.local_session") as mock_session_factory,
        ):
            ctx = {"redis": AsyncMock()}
            await process_telegram_callback(ctx, str(uuid7()), 42, "cq-1", "something_else:xyz")

        mock_answer.assert_called_once_with("cq-1")
        mock_session_factory.assert_not_called()
