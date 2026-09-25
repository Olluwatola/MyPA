"""Unit tests for the initial-extraction orchestrator (page.created path) — the required
scenarios: a large mocked page split into overlapping chunks with parallel calls, an item
appearing in two overlapping chunks deduplicated via embedding similarity, and an
oversized page flagged rather than silently truncated."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.notion.client import NotionBlock
from src.app.core.notion.initial_extraction import run_initial_extraction
from src.app.schemas.notion_classification import NotionChunkExtractedItem, NotionChunkExtractionResult

MODULE = "src.app.core.notion.initial_extraction"


def _block(block_id: str, text: str = "some text") -> NotionBlock:
    return NotionBlock(
        id=block_id,
        type="paragraph",
        plain_text=text,
        last_edited_time=datetime.now(UTC),
        has_children=False,
        parent={"type": "page_id", "page_id": "page-1"},
        raw={},
    )


def _item(source_block_id: str, title: str, confidence: float = 0.9) -> NotionChunkExtractedItem:
    return NotionChunkExtractedItem(
        item_type="task", title=title, confidence=confidence, source_block_id=source_block_id
    )


@pytest.fixture(autouse=True)
def no_open_goals():
    """Most tests don't care about goal linking — the user has no open goals."""
    with patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=[])) as mock_load:
        yield mock_load


class TestChunkedParallelExtraction:
    @pytest.mark.asyncio
    async def test_large_page_is_chunked_and_extracted_in_parallel(self, mock_db):
        blocks = [_block(str(i)) for i in range(40)]

        with (
            patch(f"{MODULE}.fetch_all_blocks_recursive", new=AsyncMock(return_value=blocks)),
            patch(f"{MODULE}.settings") as mock_settings,
            patch(
                f"{MODULE}.extract_chunk", new=AsyncMock(return_value=NotionChunkExtractionResult(items=[]))
            ) as mock_extract,
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
        ):
            mock_settings.NOTION_CHUNK_SIZE_BLOCKS = 18
            mock_settings.NOTION_CHUNK_OVERLAP_BLOCKS = 4
            mock_settings.NOTION_MAX_CHUNKS_PER_PAGE = 20
            mock_settings.NOTION_DEDUP_SIMILARITY_THRESHOLD = 0.9
            mock_sync.get = AsyncMock(return_value=None)
            mock_sync.create = AsyncMock(return_value={"id": uuid7()})

            await run_initial_extraction(mock_db, uuid7(), "token", "page-1")

        # 40 blocks / (18-4)=14 step -> chunks at 0,14,28 -> 3 chunks
        assert mock_extract.call_count == 3

    @pytest.mark.asyncio
    async def test_duplicate_item_across_overlapping_chunks_is_deduplicated(self, mock_db):
        blocks = [_block("shared-block", "finish the quarterly deck")]

        # Two chunks both extract the "same" fact from the shared overlapping block —
        # one at higher confidence.
        chunk_results = [
            NotionChunkExtractionResult(items=[_item("shared-block", "Finish the deck", confidence=0.95)]),
            NotionChunkExtractionResult(items=[_item("shared-block", "Finish deck", confidence=0.80)]),
        ]

        with (
            patch(f"{MODULE}.fetch_all_blocks_recursive", new=AsyncMock(return_value=blocks)),
            patch(f"{MODULE}.chunk_blocks", return_value=[blocks, blocks]),
            patch(f"{MODULE}.extract_chunk", new=AsyncMock(side_effect=chunk_results)),
            patch(f"{MODULE}.embed_text", new=AsyncMock(side_effect=[[1.0, 0.0], [1.0, 0.0]])),
            patch(f"{MODULE}.cosine_similarity", return_value=0.99),
            patch(f"{MODULE}.settings") as mock_settings,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
        ):
            mock_settings.NOTION_MAX_CHUNKS_PER_PAGE = 20
            mock_settings.NOTION_DEDUP_SIMILARITY_THRESHOLD = 0.9
            mock_sync.get = AsyncMock(return_value=None)
            mock_sync.create = AsyncMock(return_value={"id": uuid7()})

            await run_initial_extraction(mock_db, uuid7(), "token", "page-1")

        # Only ONE block-level persistence call, with exactly one surviving item —
        # the duplicate (lower-confidence) candidate is dropped, not double-created.
        mock_persist.assert_called_once()
        call_args = mock_persist.call_args
        actions = call_args.args[5] if len(call_args.args) > 5 else call_args.kwargs["actions"]
        assert len(actions) == 1
        assert actions[0].title == "Finish the deck"  # the higher-confidence version won

    @pytest.mark.asyncio
    async def test_oversized_page_is_flagged_not_silently_truncated(self, mock_db):
        blocks = [_block(str(i)) for i in range(500)]

        with (
            patch(f"{MODULE}.fetch_all_blocks_recursive", new=AsyncMock(return_value=blocks)),
            patch(f"{MODULE}.settings") as mock_settings,
            patch(f"{MODULE}.extract_chunk", new=AsyncMock()) as mock_extract,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
            patch(f"{MODULE}.crud_memory_extraction_records") as mock_records,
        ):
            mock_settings.NOTION_CHUNK_SIZE_BLOCKS = 18
            mock_settings.NOTION_CHUNK_OVERLAP_BLOCKS = 4
            mock_settings.NOTION_MAX_CHUNKS_PER_PAGE = 5  # deliberately tiny to force the ceiling
            mock_records.create = AsyncMock()

            await run_initial_extraction(mock_db, uuid7(), "token", "page-1")

        mock_extract.assert_not_called()
        mock_persist.assert_not_called()
        mock_records.create.assert_called_once()  # the one flag record, nothing else


class TestInitialExtractionGoalLink:
    """A confident task from a new page is linked to an open goal; open goals are loaded
    once per page and passed to every chunk call."""

    @pytest.mark.asyncio
    async def test_open_goals_passed_to_chunks_and_confident_link_kept(self, mock_db):
        goal_id = uuid7()
        open_goals = [{"id": goal_id, "title": "Launch ClientPal", "description": None, "horizon": None}]
        blocks = [_block("b1", "draft the landing page")]
        linked = NotionChunkExtractedItem(
            item_type="task",
            title="Draft landing page",
            confidence=0.9,
            source_block_id="b1",
            goal_ref=1,
            goal_link_confidence=0.9,
        )

        with (
            patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=open_goals)) as mock_load,
            patch(f"{MODULE}.fetch_all_blocks_recursive", new=AsyncMock(return_value=blocks)),
            patch(f"{MODULE}.chunk_blocks", return_value=[blocks]),
            patch(
                f"{MODULE}.extract_chunk", new=AsyncMock(return_value=NotionChunkExtractionResult(items=[linked]))
            ) as mock_extract,
            patch(f"{MODULE}.embed_text", new=AsyncMock(return_value=[1.0, 0.0])),
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
        ):
            mock_sync.get = AsyncMock(return_value=None)
            mock_sync.create = AsyncMock(return_value={"id": uuid7()})
            await run_initial_extraction(mock_db, uuid7(), "token", "page-1")

        mock_load.assert_awaited_once()
        assert mock_extract.call_args.args[2] == open_goals
        assert mock_persist.call_args.args[5][0].goal_id == goal_id
