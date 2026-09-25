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
        # quick-pick candidates are open, non-deleted goals only
        goal_filters = mock_goals.get_multi.call_args.kwargs
        assert goal_filters["status"] == "open" and goal_filters["is_deleted"] is False


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
            patch(f"{TELEGRAM_JOBS_MODULE}.crud_goals") as mock_goals,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_sync.update = AsyncMock()
            mock_goals.get = AsyncMock(return_value={"id": goal_id})
            ctx = {"redis": AsyncMock()}

            await process_telegram_callback(ctx, str(pending["user_id"]), 42, "cq-1", f"notion_goal:{goal_id}")

        mock_answer.assert_called_once_with("cq-1")
        mock_persist.assert_called_once()
        mock_sync.update.assert_called_once()
        goal_filters = mock_goals.get.call_args.kwargs
        assert goal_filters["user_id"] == pending["user_id"] and goal_filters["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_callback_for_deleted_or_foreign_goal_is_not_linked(self):
        """The tapped goal was deleted since the question was sent (or the callback data
        names someone else's goal): nothing is linked, the question stays pending."""
        from src.app.core.telegram.jobs import GOAL_UNAVAILABLE_MESSAGE, process_telegram_callback

        pending = {"id": uuid7(), "user_id": uuid7(), "notion_block_id": "block-1", "notion_page_id": "page-1"}
        with (
            patch(f"{TELEGRAM_JOBS_MODULE}.telegram_answer_callback_query", new=AsyncMock()),
            patch(f"{TELEGRAM_JOBS_MODULE}.local_session") as mock_session_factory,
            patch(f"{TELEGRAM_JOBS_MODULE}.get_oldest_pending_clarification", new=AsyncMock(return_value=pending)),
            patch(f"{TELEGRAM_JOBS_MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
            patch(f"{TELEGRAM_JOBS_MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{TELEGRAM_JOBS_MODULE}.crud_goals") as mock_goals,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_sync.update = AsyncMock()
            mock_goals.get = AsyncMock(return_value=None)
            ctx = {"redis": AsyncMock()}

            await process_telegram_callback(ctx, str(pending["user_id"]), 42, "cq-1", f"notion_goal:{uuid7()}")

        mock_persist.assert_not_called()
        mock_sync.update.assert_not_called()
        ctx["redis"].enqueue_job.assert_called_once_with("send_telegram_message", 42, GOAL_UNAVAILABLE_MESSAGE)

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


class TestResolvePendingClarification:
    async def _actions(self, mock_db, matched_goal_id, candidate_goals):
        from src.app.core.telegram.jobs import _resolve_pending_clarification
        from src.app.schemas.notion_classification import NotionClarificationResolution

        pending = {"id": uuid7(), "user_id": uuid7(), "notion_block_id": "block-1", "notion_page_id": "page-1"}
        with (
            patch(f"{TELEGRAM_JOBS_MODULE}.crud_goals") as mock_goals,
            patch(
                f"{TELEGRAM_JOBS_MODULE}.resolve_clarification_reply",
                new=AsyncMock(return_value=NotionClarificationResolution(matched_existing_goal_id=matched_goal_id)),
            ),
            patch(f"{TELEGRAM_JOBS_MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
            patch(f"{TELEGRAM_JOBS_MODULE}.crud_notion_block_sync") as mock_sync,
        ):
            mock_goals.get_multi = AsyncMock(return_value={"data": candidate_goals})
            mock_sync.update = AsyncMock()
            await _resolve_pending_clarification(mock_db, AsyncMock(), 42, pending, "the redesign one")
        return mock_persist.call_args.args[5], mock_goals.get_multi.call_args.kwargs

    @pytest.mark.asyncio
    async def test_goal_it_was_shown_is_linked(self, mock_db):
        goal_id = uuid7()
        actions, filters = await self._actions(mock_db, goal_id, [{"id": goal_id, "title": "Redesign"}])
        assert [(a.kind, a.item_id) for a in actions] == [("link", goal_id)]
        assert filters["is_deleted"] is False and filters["status"] == "open"

    @pytest.mark.asyncio
    async def test_goal_id_it_was_not_shown_is_ignored(self, mock_db):
        actions, _ = await self._actions(mock_db, uuid7(), [{"id": uuid7(), "title": "Redesign"}])
        assert actions == []
