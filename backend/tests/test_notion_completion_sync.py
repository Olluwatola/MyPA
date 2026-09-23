"""Unit tests for bidirectional, check-before-write completion sync (see
core/notion/completion_sync.py) — both directions, including the check-before-write
no-op case in each."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

MODULE = "src.app.core.notion.completion_sync"


class TestDetermineDesiredCheckedState:
    @pytest.mark.asyncio
    async def test_false_when_no_linked_items(self, mock_db):
        from src.app.core.notion.completion_sync import determine_desired_checked_state

        with patch(f"{MODULE}.crud_notion_block_link") as mock_link:
            mock_link.get_multi = AsyncMock(return_value={"data": []})
            result = await determine_desired_checked_state(mock_db, uuid7(), "block-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_true_only_when_every_linked_item_is_done(self, mock_db):
        from src.app.core.notion.completion_sync import determine_desired_checked_state

        links = [{"item_type": "task", "item_id": uuid7()}, {"item_type": "goal", "item_id": uuid7()}]
        with (
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
            patch(f"{MODULE}.crud_goals") as mock_goals,
        ):
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(return_value={"status": "done"})
            mock_goals.get = AsyncMock(return_value={"status": "open"})  # one not done
            result = await determine_desired_checked_state(mock_db, uuid7(), "block-1")
        assert result is False

        with (
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
            patch(f"{MODULE}.crud_goals") as mock_goals,
        ):
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(return_value={"status": "done"})
            mock_goals.get = AsyncMock(return_value={"status": "done"})
            result = await determine_desired_checked_state(mock_db, uuid7(), "block-1")
        assert result is True


class TestSyncCheckboxFromNotion:
    @pytest.mark.asyncio
    async def test_notion_to_app_check_before_write_skips_matching_items(self, mock_db):
        from src.app.core.notion.completion_sync import sync_checkbox_from_notion

        links = [{"item_type": "task", "item_id": uuid7()}]
        with (
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
        ):
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(return_value={"status": "done"})  # already matches
            mock_tasks.update = AsyncMock()

            await sync_checkbox_from_notion(mock_db, uuid7(), "block-1", checked=True)

        mock_tasks.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_notion_to_app_writes_when_status_differs(self, mock_db):
        from src.app.core.notion.completion_sync import sync_checkbox_from_notion

        item_id = uuid7()
        links = [{"item_type": "task", "item_id": item_id}]
        with (
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
        ):
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(return_value={"status": "open"})
            mock_tasks.update = AsyncMock()

            await sync_checkbox_from_notion(mock_db, uuid7(), "block-1", checked=True)

        mock_tasks.update.assert_called_once_with(db=mock_db, object={"status": "done"}, id=item_id)


class TestSyncStatusToNotion:
    @pytest.mark.asyncio
    async def test_unlinked_item_is_a_no_op(self):
        from src.app.core.notion.completion_sync import sync_status_to_notion

        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.get_block", new=AsyncMock()) as mock_get_block,
        ):
            mock_db = AsyncMock()
            mock_session_factory.return_value.__aenter__.return_value = mock_db
            mock_link.get = AsyncMock(return_value=None)

            await sync_status_to_notion({}, "task", str(uuid7()))

        mock_get_block.assert_not_called()

    @pytest.mark.asyncio
    async def test_app_to_notion_check_before_write_skips_when_already_matching(self):
        from src.app.core.notion.client import NotionBlock
        from src.app.core.notion.completion_sync import sync_status_to_notion

        link = {"user_id": uuid7(), "notion_block_id": "block-1"}
        current_block = NotionBlock(
            id="block-1", type="to_do", plain_text="x", last_edited_time=datetime.now(UTC), has_children=False,
            parent={}, raw={"to_do": {"checked": True}},
        )
        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link_crud,
            patch(f"{MODULE}.crud_notion_connection") as mock_conn_crud,
            patch(f"{MODULE}.decrypt_token", return_value="token"),
            patch(f"{MODULE}.determine_desired_checked_state", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.get_block", new=AsyncMock(return_value=current_block)),
            patch(f"{MODULE}.update_block_checkbox", new=AsyncMock()) as mock_update,
        ):
            mock_db = AsyncMock()
            mock_session_factory.return_value.__aenter__.return_value = mock_db
            mock_link_crud.get = AsyncMock(return_value=link)
            mock_conn_crud.get = AsyncMock(return_value={"access_token": "enc"})

            await sync_status_to_notion({}, "task", str(uuid7()))

        mock_update.assert_not_called()
