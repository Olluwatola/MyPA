"""Unit tests for core/llm/conversation.py: generate_conversation_reply's exact message
ordering (system prompt -> optional memory block -> chronological history, latest turn
appearing exactly once) and tier="medium" usage; cleanup_expired_conversation_messages's
db_delete call shape."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.app.core.llm import conversation
from src.app.core.llm.provider import LlmCompletionResult, LlmUsage

MODULE = "src.app.core.llm.conversation"


def _history_rows(user_id):
    """get_multi returns DESC (most-recent-first); generate_conversation_reply reverses
    it back to chronological order before building the prompt."""
    return [
        {"role": "assistant", "content": "latest turn is most recent", "user_id": user_id},
        {"role": "user", "content": "how are you?", "user_id": user_id},
        {"role": "assistant", "content": "hi!", "user_id": user_id},
        {"role": "user", "content": "hello", "user_id": user_id},
    ]


class TestGenerateConversationReply:
    @pytest.mark.asyncio
    async def test_message_ordering_without_memory(self, mock_db):
        user_id = uuid4()
        rows = _history_rows(user_id)
        completion = LlmCompletionResult(
            text="a reply", model="m", provider="p", usage=LlmUsage(prompt_tokens=1, completion_tokens=1)
        )
        mock_llm_service = MagicMock()
        mock_llm_service.complete = AsyncMock(return_value=completion)

        with (
            patch(f"{MODULE}.crud_conversation_messages") as mock_crud,
            patch(f"{MODULE}.search_similar_memories", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.service.llm_service", mock_llm_service),
            patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=[])),
        ):
            mock_crud.get_multi = AsyncMock(return_value={"data": rows})

            result = await conversation.generate_conversation_reply(mock_db, user_id)

        assert result == "a reply"
        call_kwargs = mock_llm_service.complete.call_args.kwargs
        assert call_kwargs["tier"] == "medium"

        messages = call_kwargs["messages"]
        assert messages[0].role == "system"
        # No memory block — next message is the chronological history, oldest first,
        # ending with the latest (most-recent) turn appearing exactly once.
        history = messages[1:]
        assert [m.content for m in history] == [row["content"] for row in reversed(rows)]
        assert history[-1].content == "latest turn is most recent"
        assert sum(1 for m in history if m.content == "latest turn is most recent") == 1

    @pytest.mark.asyncio
    async def test_includes_memory_block_when_relevant_records_found(self, mock_db):
        user_id = uuid4()
        rows = _history_rows(user_id)
        completion = LlmCompletionResult(
            text="a reply", model="m", provider="p", usage=LlmUsage(prompt_tokens=1, completion_tokens=1)
        )
        mock_llm_service = MagicMock()
        mock_llm_service.complete = AsyncMock(return_value=completion)
        memory_record = MagicMock(summary="user prefers concise replies")

        with (
            patch(f"{MODULE}.crud_conversation_messages") as mock_crud,
            patch(f"{MODULE}.search_similar_memories", new=AsyncMock(return_value=[memory_record])),
            patch(f"{MODULE}.service.llm_service", mock_llm_service),
            patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=[])),
        ):
            mock_crud.get_multi = AsyncMock(return_value={"data": rows})

            await conversation.generate_conversation_reply(mock_db, user_id)

        messages = mock_llm_service.complete.call_args.kwargs["messages"]
        assert messages[0].role == "system"
        assert messages[1].role == "system"
        assert "user prefers concise replies" in messages[1].content
        assert messages[2].content == "hello"  # chronological history starts right after the memory block

    @pytest.mark.asyncio
    async def test_open_goals_are_added_as_context(self, mock_db):
        """Required proof (h), chat half: the reply sees the user's open goals. Paused,
        dropped, done and deleted goals are excluded by `load_open_goals` itself
        (tests/test_goal_context.py), the only source of this list."""
        user_id = uuid4()
        completion = LlmCompletionResult(
            text="a reply", model="m", provider="p", usage=LlmUsage(prompt_tokens=1, completion_tokens=1)
        )
        mock_llm_service = MagicMock()
        mock_llm_service.complete = AsyncMock(return_value=completion)
        goals = [{"title": "Launch ClientPal", "horizon": "short_term"}, {"title": "Read more", "horizon": None}]

        with (
            patch(f"{MODULE}.crud_conversation_messages") as mock_crud,
            patch(f"{MODULE}.search_similar_memories", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.service.llm_service", mock_llm_service),
            patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=goals)) as mock_load,
        ):
            mock_crud.get_multi = AsyncMock(return_value={"data": _history_rows(user_id)})
            await conversation.generate_conversation_reply(mock_db, user_id)

        mock_load.assert_awaited_once_with(mock_db, user_id)
        messages = mock_llm_service.complete.call_args.kwargs["messages"]
        assert messages[1].role == "system"
        assert "- Launch ClientPal (short term)" in messages[1].content
        assert "- Read more" in messages[1].content
        assert messages[2].content == "hello"


class TestCleanupExpiredConversationMessages:
    @pytest.mark.asyncio
    async def test_deletes_rows_older_than_retention_window(self, mock_db):
        with (
            patch(f"{MODULE}.local_session", new=lambda: _FakeSessionCM(mock_db)),
            patch(f"{MODULE}.crud_conversation_messages") as mock_crud,
        ):
            mock_crud.db_delete = AsyncMock()

            await conversation.cleanup_expired_conversation_messages(ctx={})

        mock_crud.db_delete.assert_called_once()
        call_kwargs = mock_crud.db_delete.call_args.kwargs
        assert call_kwargs["db"] == mock_db
        assert call_kwargs["allow_multiple"] is True

        cutoff = call_kwargs["created_at__lt"]
        expected = datetime.now(UTC) - timedelta(days=7)
        assert abs((expected - cutoff).total_seconds()) < 5


class _FakeSessionCM:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc_info):
        return False
