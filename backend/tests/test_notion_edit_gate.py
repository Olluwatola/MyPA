"""Unit tests for the edit-path 3-stage gate (core/notion/edit_gate.py) — the three
required scenarios (unchanged timestamp, minor fingerprint delta, real change) plus the
confirmed one-call-per-changed-block override (never batched)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.notion.client import NotionBlock
from src.app.core.notion.edit_gate import process_changed_block
from src.app.core.notion.simhash import compute_simhash
from src.app.schemas.notion_classification import NotionFreshClassificationResult

MODULE = "src.app.core.notion.edit_gate"


def _block(block_id: str, text: str, edited_at: datetime, block_type: str = "paragraph") -> NotionBlock:
    return NotionBlock(
        id=block_id, type=block_type, plain_text=text, last_edited_time=edited_at, has_children=False, parent={}, raw={}
    )


class TestUnchangedTimestamp:
    @pytest.mark.asyncio
    async def test_no_fetch_or_llm_call_when_timestamp_unchanged(self, mock_db):
        edited_at = datetime.now(UTC)
        block = _block("block-1", "finish the deck", edited_at)
        existing_sync = {"id": uuid7(), "last_edited_time": edited_at, "content_fingerprint": 123}

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock()) as mock_classify,
        ):
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_classify.assert_not_called()
        mock_sync.update.assert_not_called()


class TestMinorFingerprintDelta:
    @pytest.mark.asyncio
    async def test_trivial_edit_refreshes_watermark_without_llm_call(self, mock_db):
        old_text = "finish the deck for friday"
        new_text = "finish the deck for friday."  # punctuation-only edit
        old_fingerprint = compute_simhash(old_text)
        old_time = datetime(2026, 1, 1, tzinfo=UTC)
        new_time = datetime(2026, 1, 2, tzinfo=UTC)
        block = _block("block-1", new_text, new_time)
        existing_sync = {"id": uuid7(), "last_edited_time": old_time, "content_fingerprint": old_fingerprint}

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock()) as mock_classify,
            patch(f"{MODULE}.settings") as mock_settings,
        ):
            mock_settings.NOTION_EDIT_SIMHASH_UNCHANGED_THRESHOLD = 3
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_classify.assert_not_called()
        mock_sync.update.assert_called_once()
        _, kwargs = mock_sync.update.call_args
        assert kwargs["object"]["last_edited_time"] == new_time


class TestRealChange:
    @pytest.mark.asyncio
    async def test_meaningful_edit_reaches_classification(self, mock_db):
        old_text = "finish the deck"
        new_text = "schedule a dentist appointment for next month"
        old_time = datetime(2026, 1, 1, tzinfo=UTC)
        new_time = datetime(2026, 1, 2, tzinfo=UTC)
        block = _block("block-1", new_text, new_time)
        existing_sync = {
            "id": uuid7(),
            "last_edited_time": old_time,
            "content_fingerprint": compute_simhash(old_text),
        }
        fresh_result = NotionFreshClassificationResult(outcome="not_actionable", summary="not actionable")

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock(return_value=fresh_result)) as mock_classify,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
        ):
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()
            mock_link.get_multi = AsyncMock(return_value={"data": []})

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_classify.assert_called_once()
        mock_persist.assert_called_once()


class TestMultiBlockEditEvent:
    @pytest.mark.asyncio
    async def test_each_changed_block_gets_its_own_separate_classification_call(self, mock_db):
        """The confirmed 2026-09-23 override: N changed blocks in one event -> N
        classification calls, never one batched call covering all of them."""
        new_time = datetime(2026, 1, 2, tzinfo=UTC)
        blocks = [
            _block("block-1", "schedule the dentist", new_time),
            _block("block-2", "email the client about the deck", new_time),
        ]
        fresh_result = NotionFreshClassificationResult(outcome="not_actionable", summary="x")

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock(return_value=fresh_result)) as mock_classify,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()),
        ):
            mock_sync.get = AsyncMock(return_value=None)  # never seen before -> always classify
            mock_sync.create = AsyncMock(return_value={"id": uuid7()})
            mock_link.get_multi = AsyncMock(return_value={"data": []})

            for block in blocks:
                await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", block.id, blocks)

        assert mock_classify.call_count == 2
