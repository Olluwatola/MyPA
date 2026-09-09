"""Unit test for search_similar_memories's DB-call shape — the real pgvector ranking
behavior (two unrelated pieces of content, checking rank order) is verified manually
against a live Postgres per project-manager verification steps, not here."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.app.core.llm import retrieval


class TestSearchSimilarMemories:
    @pytest.mark.asyncio
    async def test_embeds_query_and_returns_the_executed_selects_records(self, mock_db):
        user_id = uuid4()
        fake_records = [MagicMock(), MagicMock()]

        scalars_result = MagicMock()
        scalars_result.all.return_value = fake_records
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        mock_db.execute = AsyncMock(return_value=execute_result)

        with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.1] * 384)) as mock_embed:
            result = await retrieval.search_similar_memories(mock_db, user_id, "what did I say about milk?")

        mock_embed.assert_called_once_with("what did I say about milk?")
        mock_db.execute.assert_called_once()
        assert result == fake_records

    @pytest.mark.asyncio
    async def test_explicit_top_k_is_accepted(self, mock_db):
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        mock_db.execute = AsyncMock(return_value=execute_result)

        with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.1] * 384)):
            result = await retrieval.search_similar_memories(mock_db, uuid4(), "query", top_k=2)

        assert result == []
        mock_db.execute.assert_called_once()
