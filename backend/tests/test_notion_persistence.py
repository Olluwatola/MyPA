"""Unit tests for `core/notion/persistence.py` — Notion re-classification never overwrites a
field the user set by hand (sticky flags), never touches a soft-deleted task or goal, and
the create path writes a goal's date as `target_date` and a task's accepted AI goal link."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.items.sticky import GOAL_STICKY_FLAGS
from src.app.core.notion.persistence import NotionPersistenceAction, _create_item, _update_item

MODULE = "src.app.core.notion.persistence"

ALL_FIELDS = {"title": "New title", "description": "New desc", "urgency": "high", "effort_level": "passive"}
TASK_CONTENT_FLAGS = {
    "title": "title_manually_set",
    "description": "description_manually_set",
    "urgency": "urgency_manually_set",
    "effort_level": "effort_level_manually_set",
}
GOAL_FIELDS = {"title": "New title", "description": "New desc"}


def _action(item_type: str = "task") -> NotionPersistenceAction:
    return NotionPersistenceAction(kind="update", item_type=item_type, item_id=uuid7(), **ALL_FIELDS)  # type: ignore[arg-type]


def _task(**overrides) -> dict:
    return (
        {"is_deleted": False, "goal_id_manually_set": False}
        | dict.fromkeys(TASK_CONTENT_FLAGS.values(), False)
        | overrides
    )


def _goal(**overrides) -> dict:
    return {"is_deleted": False} | dict.fromkeys(GOAL_STICKY_FLAGS.values(), False) | overrides


class TestUpdateItemSticky:
    @pytest.mark.parametrize(("field", "flag"), list(TASK_CONTENT_FLAGS.items()))
    @pytest.mark.asyncio
    async def test_flag_blocks_only_its_own_field(self, mock_db, field, flag):
        action = _action()
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=_task(**{flag: True}))
            mock_crud.update = AsyncMock()
            await _update_item(mock_db, action)

        expected = {key: value for key, value in ALL_FIELDS.items() if key != field}
        mock_crud.update.assert_called_once_with(db=mock_db, object=expected, id=action.item_id, commit=False)

    @pytest.mark.asyncio
    async def test_all_flags_set_means_no_update(self, mock_db):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=_task(**dict.fromkeys(TASK_CONTENT_FLAGS.values(), True)))
            mock_crud.update = AsyncMock()
            await _update_item(mock_db, _action())
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_flags_updates_everything_but_never_goal_id(self, mock_db):
        action = _action()
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=_task())
            mock_crud.update = AsyncMock()
            await _update_item(mock_db, action)
        assert mock_crud.update.call_args.kwargs["object"] == ALL_FIELDS


class TestUpdateItemDeleted:
    @pytest.mark.asyncio
    async def test_update_on_deleted_task_is_noop(self, mock_db):
        action = _action()
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=_task(is_deleted=True))
            mock_crud.update = AsyncMock()
            await _update_item(mock_db, action)

        # read without an is_deleted filter, so the deleted row is seen and skipped
        assert "is_deleted" not in mock_crud.get.call_args.kwargs
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_task_is_noop(self, mock_db):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            mock_crud.update = AsyncMock()
            await _update_item(mock_db, _action())
        mock_crud.update.assert_not_called()


class TestUpdateItemGoal:
    """Required proof (c): sticky title/description block Notion's overwrite."""

    @pytest.mark.asyncio
    async def test_goal_update_applies_only_title_and_description(self, mock_db):
        action = _action(item_type="goal")
        with patch(f"{MODULE}.crud_goals") as mock_goals, patch(f"{MODULE}.crud_tasks") as mock_tasks:
            mock_goals.get = AsyncMock(return_value=_goal())
            mock_goals.update = AsyncMock()
            mock_tasks.get = AsyncMock()
            await _update_item(mock_db, action)

        mock_goals.update.assert_called_once_with(db=mock_db, object=GOAL_FIELDS, id=action.item_id, commit=False)
        mock_tasks.get.assert_not_called()

    @pytest.mark.parametrize(("field", "flag"), list(GOAL_STICKY_FLAGS.items()))
    @pytest.mark.asyncio
    async def test_goal_flag_blocks_only_its_own_field(self, mock_db, field, flag):
        action = _action(item_type="goal")
        with patch(f"{MODULE}.crud_goals") as mock_goals:
            mock_goals.get = AsyncMock(return_value=_goal(**{flag: True}))
            mock_goals.update = AsyncMock()
            await _update_item(mock_db, action)

        expected = {key: value for key, value in GOAL_FIELDS.items() if key != field}
        assert mock_goals.update.call_args.kwargs["object"] == expected

    @pytest.mark.asyncio
    async def test_both_goal_flags_set_means_no_update(self, mock_db):
        with patch(f"{MODULE}.crud_goals") as mock_goals:
            mock_goals.get = AsyncMock(return_value=_goal(title_manually_set=True, description_manually_set=True))
            mock_goals.update = AsyncMock()
            await _update_item(mock_db, _action(item_type="goal"))
        mock_goals.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_on_deleted_goal_is_noop(self, mock_db):
        with patch(f"{MODULE}.crud_goals") as mock_goals:
            mock_goals.get = AsyncMock(return_value=_goal(is_deleted=True))
            mock_goals.update = AsyncMock()
            await _update_item(mock_db, _action(item_type="goal"))
        assert "is_deleted" not in mock_goals.get.call_args.kwargs
        mock_goals.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_goal_is_noop(self, mock_db):
        with patch(f"{MODULE}.crud_goals") as mock_goals:
            mock_goals.get = AsyncMock(return_value=None)
            mock_goals.update = AsyncMock()
            await _update_item(mock_db, _action(item_type="goal"))
        mock_goals.update.assert_not_called()


class TestCreateItem:
    @pytest.mark.asyncio
    async def test_goal_create_writes_target_date_not_due_date(self, mock_db):
        action = NotionPersistenceAction(
            kind="create", item_type="goal", title="Run a marathon", due_date=date(2027, 4, 1), confidence=0.9
        )
        with (
            patch(f"{MODULE}.crud_goals") as mock_goals,
            patch(f"{MODULE}.crud_notion_block_link") as mock_links,
        ):
            mock_goals.create = AsyncMock(return_value={"id": uuid7()})
            mock_links.create = AsyncMock()
            await _create_item(mock_db, uuid7(), "block-1", uuid7(), action)

        created = mock_goals.create.call_args.kwargs["object"]
        assert created.target_date == date(2027, 4, 1)
        assert "due_date" not in created.model_dump()

    @pytest.mark.asyncio
    async def test_task_create_carries_accepted_goal_link(self, mock_db):
        goal_id = uuid7()
        action = NotionPersistenceAction(
            kind="create", item_type="task", title="Draft landing page", confidence=0.9, goal_id=goal_id
        )
        with (
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
            patch(f"{MODULE}.crud_notion_block_link", MagicMock(create=AsyncMock())),
        ):
            mock_tasks.create = AsyncMock(return_value={"id": uuid7()})
            await _create_item(mock_db, uuid7(), "block-1", uuid7(), action)

        created = mock_tasks.create.call_args.kwargs["object"]
        assert created.goal_id == goal_id
        assert created.goal_id_manually_set is False
