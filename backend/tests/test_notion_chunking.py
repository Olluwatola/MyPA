"""Unit tests for the initial-extraction chunking window (page.created path only — see
core/notion/chunking.py). Pure function, no I/O."""

from datetime import UTC, datetime

import pytest

from src.app.core.notion.chunking import chunk_blocks
from src.app.core.notion.client import NotionBlock


def _block(block_id: str) -> NotionBlock:
    return NotionBlock(
        id=block_id,
        type="paragraph",
        plain_text=f"text for {block_id}",
        last_edited_time=datetime.now(UTC),
        has_children=False,
        parent={},
        raw={},
    )


class TestChunkBlocks:
    def test_empty_blocks_produce_no_chunks(self):
        assert chunk_blocks([]) == []

    def test_short_page_produces_a_single_chunk(self):
        blocks = [_block(str(i)) for i in range(5)]
        chunks = chunk_blocks(blocks, chunk_size=18, overlap=4)
        assert len(chunks) == 1
        assert chunks[0] == blocks

    def test_exact_window_boundaries(self):
        blocks = [_block(str(i)) for i in range(20)]
        chunks = chunk_blocks(blocks, chunk_size=10, overlap=2)
        # step = 8: windows start at 0, 8, 16
        assert [b.id for b in chunks[0]] == [str(i) for i in range(0, 10)]
        assert [b.id for b in chunks[1]] == [str(i) for i in range(8, 18)]
        assert [b.id for b in chunks[2]] == [str(i) for i in range(16, 20)]

    def test_overlap_correctness(self):
        blocks = [_block(str(i)) for i in range(20)]
        chunks = chunk_blocks(blocks, chunk_size=10, overlap=2)
        overlap_ids = {b.id for b in chunks[0]} & {b.id for b in chunks[1]}
        assert overlap_ids == {"8", "9"}

    def test_chunk_size_must_exceed_overlap(self):
        with pytest.raises(ValueError):
            chunk_blocks([_block("1")], chunk_size=5, overlap=5)

    def test_uses_settings_defaults_when_unspecified(self):
        blocks = [_block(str(i)) for i in range(50)]
        chunks = chunk_blocks(blocks)
        assert len(chunks) > 1
        assert all(len(chunk) <= 18 for chunk in chunks)
