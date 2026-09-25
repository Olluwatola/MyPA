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
    async def test_none_when_no_linked_items(self, mock_db):
        from src.app.core.notion.completion_sync import determine_desired_checked_state

        with patch(f"{MODULE}.crud_notion_block_link") as mock_link:
            mock_link.get_multi = AsyncMock(return_value={"data": []})
            result = await determine_desired_checked_state(mock_db, uuid7(), "block-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_deleted_task_ignored(self, mock_db):
        """One deleted (still-linked) open task must not block the checkbox once every
        live item is done."""
        from src.app.core.notion.completion_sync import determine_desired_checked_state

        deleted_id, live_id = uuid7(), uuid7()
        links = [{"item_type": "task", "item_id": deleted_id}, {"item_type": "task", "item_id": live_id}]
        rows = {
            deleted_id: {"status": "open", "is_deleted": True},
            live_id: {"status": "done", "is_deleted": False},
        }
        with (
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
        ):
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(side_effect=lambda db, id: rows[id])
            result = await determine_desired_checked_state(mock_db, uuid7(), "block-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_only_deleted_returns_none(self, mock_db):
        from src.app.core.notion.completion_sync import determine_desired_checked_state

        links = [{"item_type": "task", "item_id": uuid7()}]
        with (
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
        ):
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(return_value={"status": "done", "is_deleted": True})
            result = await determine_desired_checked_state(mock_db, uuid7(), "block-1")
        assert result is None

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
            mock_tasks.get = AsyncMock(return_value={"status": "done", "is_deleted": False})
            mock_goals.get = AsyncMock(return_value={"status": "open", "is_deleted": False})  # one not done
            result = await determine_desired_checked_state(mock_db, uuid7(), "block-1")
        assert result is False

        with (
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
            patch(f"{MODULE}.crud_goals") as mock_goals,
        ):
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(return_value={"status": "done", "is_deleted": False})
            mock_goals.get = AsyncMock(return_value={"status": "done", "is_deleted": False})
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
            mock_tasks.get = AsyncMock(return_value={"status": "done", "is_deleted": False})  # already matches
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
            mock_tasks.get = AsyncMock(return_value={"status": "open", "is_deleted": False})
            mock_tasks.update = AsyncMock()

            await sync_checkbox_from_notion(mock_db, uuid7(), "block-1", checked=True)

        mock_tasks.update.assert_called_once_with(db=mock_db, object={"status": "done"}, id=item_id)

    @pytest.mark.asyncio
    async def test_deleted_task_not_revived(self, mock_db):
        from src.app.core.notion.completion_sync import sync_checkbox_from_notion

        deleted_id, live_id = uuid7(), uuid7()
        links = [{"item_type": "task", "item_id": deleted_id}, {"item_type": "task", "item_id": live_id}]
        rows = {
            deleted_id: {"status": "open", "is_deleted": True},
            live_id: {"status": "open", "is_deleted": False},
        }
        with (
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
        ):
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(side_effect=lambda db, id: rows[id])
            mock_tasks.update = AsyncMock()

            await sync_checkbox_from_notion(mock_db, uuid7(), "block-1", checked=True)

        mock_tasks.update.assert_called_once_with(db=mock_db, object={"status": "done"}, id=live_id)


def _linked_rows_patches(rows: dict):
    """Patches the link table + both CRUDs so each linked item resolves to `rows[item_id]`."""
    links = [{"item_type": item_type, "item_id": item_id} for item_id, (item_type, _) in rows.items()]
    mock_link = patch(f"{MODULE}.crud_notion_block_link")
    mock_tasks = patch(f"{MODULE}.crud_tasks")
    mock_goals = patch(f"{MODULE}.crud_goals")
    return links, mock_link, mock_tasks, mock_goals


class TestGoalStatusesInCompletionSync:
    """The paused/dropped checkbox rules (decisions-log.md 2026-09-24): dropped is ignored
    like deleted; paused counts as not done; tick -> paused becomes done; untick -> only
    done items reopen."""

    async def _desired(self, mock_db, rows: dict):
        from src.app.core.notion.completion_sync import determine_desired_checked_state

        links, link_patch, tasks_patch, goals_patch = _linked_rows_patches(rows)
        with link_patch as mock_link, tasks_patch as mock_tasks, goals_patch as mock_goals:
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(side_effect=lambda db, id: rows[id][1])
            mock_goals.get = AsyncMock(side_effect=lambda db, id: rows[id][1])
            return await determine_desired_checked_state(mock_db, uuid7(), "block-1")

    async def _sync(self, mock_db, rows: dict, checked: bool):
        from src.app.core.notion.completion_sync import sync_checkbox_from_notion

        links, link_patch, tasks_patch, goals_patch = _linked_rows_patches(rows)
        with link_patch as mock_link, tasks_patch as mock_tasks, goals_patch as mock_goals:
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(side_effect=lambda db, id: rows[id][1])
            mock_goals.get = AsyncMock(side_effect=lambda db, id: rows[id][1])
            mock_tasks.update = AsyncMock()
            mock_goals.update = AsyncMock()
            await sync_checkbox_from_notion(mock_db, uuid7(), "block-1", checked=checked)
        return mock_tasks.update, mock_goals.update

    @pytest.mark.asyncio
    async def test_dropped_goal_is_ignored_so_done_task_ticks_the_box(self, mock_db):
        rows = {
            uuid7(): ("goal", {"status": "dropped", "is_deleted": False}),
            uuid7(): ("task", {"status": "done", "is_deleted": False}),
        }
        assert await self._desired(mock_db, rows) is True

    @pytest.mark.asyncio
    async def test_only_a_dropped_goal_means_nothing_to_decide(self, mock_db):
        rows = {uuid7(): ("goal", {"status": "dropped", "is_deleted": False})}
        assert await self._desired(mock_db, rows) is None

    @pytest.mark.asyncio
    async def test_paused_goal_counts_as_not_done(self, mock_db):
        rows = {
            uuid7(): ("goal", {"status": "paused", "is_deleted": False}),
            uuid7(): ("task", {"status": "done", "is_deleted": False}),
        }
        assert await self._desired(mock_db, rows) is False

    @pytest.mark.asyncio
    async def test_deleted_goal_is_ignored(self, mock_db):
        rows = {
            uuid7(): ("goal", {"status": "open", "is_deleted": True}),
            uuid7(): ("task", {"status": "done", "is_deleted": False}),
        }
        assert await self._desired(mock_db, rows) is True

    @pytest.mark.asyncio
    async def test_tick_marks_paused_goal_done_and_leaves_dropped_alone(self, mock_db):
        paused_id, dropped_id = uuid7(), uuid7()
        rows = {
            paused_id: ("goal", {"status": "paused", "is_deleted": False}),
            dropped_id: ("goal", {"status": "dropped", "is_deleted": False}),
        }
        _, goals_update = await self._sync(mock_db, rows, checked=True)
        goals_update.assert_called_once_with(db=mock_db, object={"status": "done"}, id=paused_id)

    @pytest.mark.asyncio
    async def test_untick_only_reopens_done_items(self, mock_db):
        """The stage-0 fix: a text edit on an unticked line must not flip a paused goal
        back to open."""
        done_id = uuid7()
        rows = {
            uuid7(): ("goal", {"status": "paused", "is_deleted": False}),
            uuid7(): ("goal", {"status": "dropped", "is_deleted": False}),
            done_id: ("goal", {"status": "done", "is_deleted": False}),
        }
        _, goals_update = await self._sync(mock_db, rows, checked=False)
        goals_update.assert_called_once_with(db=mock_db, object={"status": "open"}, id=done_id)

    @pytest.mark.asyncio
    async def test_untick_leaves_open_items_alone(self, mock_db):
        rows = {uuid7(): ("task", {"status": "open", "is_deleted": False})}
        tasks_update, _ = await self._sync(mock_db, rows, checked=False)
        tasks_update.assert_not_called()


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
            id="block-1",
            type="to_do",
            plain_text="x",
            last_edited_time=datetime.now(UTC),
            has_children=False,
            parent={},
            raw={"to_do": {"checked": True}},
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

    @pytest.mark.asyncio
    async def test_no_live_items_no_notion_write(self):
        """Deleting a task never changes Notion — if every linked item is deleted, the job
        doesn't even read the block."""
        from src.app.core.notion.completion_sync import sync_status_to_notion

        link = {"user_id": uuid7(), "notion_block_id": "block-1"}
        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link_crud,
            patch(f"{MODULE}.crud_notion_connection") as mock_conn_crud,
            patch(f"{MODULE}.decrypt_token", return_value="token"),
            patch(f"{MODULE}.determine_desired_checked_state", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.get_block", new=AsyncMock()) as mock_get_block,
            patch(f"{MODULE}.update_block_checkbox", new=AsyncMock()) as mock_update,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_link_crud.get = AsyncMock(return_value=link)
            mock_conn_crud.get = AsyncMock(return_value={"access_token": "enc"})

            await sync_status_to_notion({}, "task", str(uuid7()))

        mock_get_block.assert_not_called()
        mock_update.assert_not_called()
