"""Unit tests for task-id tagging/untagging (core/notion/tagging.py) — built now as a
genuine, tested capability with no live caller yet (mirrors build_inline_keyboard's
1.6 precedent). Covers the already-to_do (no conversion) and plain-list-item
(conversion) paths, plus untag deleting only the link row."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.notion.client import NotionBlock

MODULE = "src.app.core.notion.tagging"


def _block(block_type: str, block_id: str = "block-1") -> NotionBlock:
    raw = {block_type: {"rich_text": [{"plain_text": "some text"}]}} if block_type != "to_do" else {}
    return NotionBlock(
        id=block_id,
        type=block_type,
        plain_text="some text",
        last_edited_time=datetime.now(UTC),
        has_children=False,
        parent={"type": "page_id", "page_id": "page-1"},
        raw=raw,
    )


class TestTagBlockAlreadyToDo:
    @pytest.mark.asyncio
    async def test_no_conversion_when_already_to_do(self, mock_db):
        from src.app.core.notion.tagging import tag_block

        item_id = uuid7()
        with (
            patch(f"{MODULE}.get_block", new=AsyncMock(return_value=_block("to_do"))),
            patch(f"{MODULE}.append_block", new=AsyncMock()) as mock_append,
            patch(f"{MODULE}.delete_block", new=AsyncMock()) as mock_delete,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
        ):
            mock_link.get = AsyncMock(return_value=None)
            mock_link.create = AsyncMock()
            mock_db.commit = AsyncMock()

            final_id = await tag_block(mock_db, uuid7(), "token", "block-1", "task", item_id)

        mock_append.assert_not_called()
        mock_delete.assert_not_called()
        assert final_id == "block-1"
        mock_link.create.assert_called_once()


class TestTagBlockPlainListItem:
    @pytest.mark.asyncio
    async def test_converts_plain_list_item_to_to_do(self, mock_db):
        from src.app.core.notion.tagging import tag_block

        item_id = uuid7()
        new_block = _block("to_do", block_id="block-2")
        with (
            patch(f"{MODULE}.get_block", new=AsyncMock(return_value=_block("bulleted_list_item"))),
            patch(f"{MODULE}.append_block", new=AsyncMock(return_value=new_block)) as mock_append,
            patch(f"{MODULE}.delete_block", new=AsyncMock()) as mock_delete,
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
        ):
            mock_sync.get = AsyncMock(return_value=None)
            mock_sync.create = AsyncMock()
            mock_sync.db_delete = AsyncMock()
            mock_link.get_multi = AsyncMock(return_value={"data": []})
            mock_link.get = AsyncMock(return_value=None)
            mock_link.create = AsyncMock()
            mock_db.commit = AsyncMock()

            final_id = await tag_block(mock_db, uuid7(), "token", "block-1", "task", item_id)

        mock_append.assert_called_once()
        mock_delete.assert_called_once_with("token", "block-1")
        assert final_id == "block-2"  # identity changed — caller must persist this


class TestUntagBlock:
    @pytest.mark.asyncio
    async def test_untag_deletes_only_the_link_row(self, mock_db):
        from src.app.core.notion.tagging import untag_block

        link = {"id": uuid7()}
        with patch(f"{MODULE}.crud_notion_block_link") as mock_link:
            mock_link.get = AsyncMock(return_value=link)
            mock_link.db_delete = AsyncMock()

            await untag_block(mock_db, uuid7(), "task", uuid7())

        mock_link.db_delete.assert_called_once_with(db=mock_db, id=link["id"])
