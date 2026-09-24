"""Unit tests for `core/notion/persistence.py::_update_item` — Notion re-classification
never overwrites a field the user set by hand (sticky flags), and never touches a
soft-deleted task."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.notion.persistence import NotionPersistenceAction, _update_item
from src.app.core.tasks.sticky import STICKY_FLAG_BY_FIELD

MODULE = "src.app.core.notion.persistence"

ALL_FIELDS = {"title": "New title", "description": "New desc", "urgency": "high", "effort_level": "passive"}


def _action(item_type: str = "task") -> NotionPersistenceAction:
    return NotionPersistenceAction(kind="update", item_type=item_type, item_id=uuid7(), **ALL_FIELDS)  # type: ignore[arg-type]


def _task(**overrides) -> dict:
    return {"is_deleted": False} | dict.fromkeys(STICKY_FLAG_BY_FIELD.values(), False) | overrides


class TestUpdateItemSticky:
    @pytest.mark.parametrize(("field", "flag"), list(STICKY_FLAG_BY_FIELD.items()))
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
            mock_crud.get = AsyncMock(return_value=_task(**dict.fromkeys(STICKY_FLAG_BY_FIELD.values(), True)))
            mock_crud.update = AsyncMock()
            await _update_item(mock_db, _action())
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_flags_updates_everything(self, mock_db):
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
    @pytest.mark.asyncio
    async def test_goal_update_unchanged(self, mock_db):
        action = _action(item_type="goal")
        with patch(f"{MODULE}.crud_goals") as mock_goals, patch(f"{MODULE}.crud_tasks") as mock_tasks:
            mock_goals.update = AsyncMock()
            mock_tasks.get = AsyncMock()
            await _update_item(mock_db, action)

        mock_goals.update.assert_called_once_with(
            db=mock_db, object={"title": "New title", "description": "New desc"}, id=action.item_id, commit=False
        )
        mock_tasks.get.assert_not_called()
