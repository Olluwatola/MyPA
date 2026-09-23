"""Unit tests for the status-only goal update endpoint — mirrors test_tasks.py's shape."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.api.v1.goals import GoalStatusUpdate, patch_goal_status
from src.app.core.exceptions.http_exceptions import ForbiddenException, NotFoundException

MODULE = "src.app.api.v1.goals"


class TestPatchGoalStatus:
    @pytest.mark.asyncio
    async def test_missing_goal_raises_not_found(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundException):
                await patch_goal_status(
                    goal_id=uuid7(),
                    body=GoalStatusUpdate(status="done"),
                    current_user=current_user_dict,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_other_users_goal_raises_forbidden(self, mock_db, current_user_dict):
        goal = {"user_id": uuid7(), "status": "open"}
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=goal)
            with pytest.raises(ForbiddenException):
                await patch_goal_status(
                    goal_id=uuid7(),
                    body=GoalStatusUpdate(status="done"),
                    current_user=current_user_dict,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_updates_status_and_enqueues_notion_sync_unconditionally(self, mock_db, current_user_dict):
        goal_id = uuid7()
        goal = {"user_id": current_user_dict["id"], "status": "open"}
        with (
            patch(f"{MODULE}.crud_goals") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=goal)
            mock_crud.update = AsyncMock(return_value={"status": "done"})
            mock_queue.pool.enqueue_job = AsyncMock()

            result = await patch_goal_status(
                goal_id=goal_id, body=GoalStatusUpdate(status="done"), current_user=current_user_dict, db=mock_db
            )

        assert result["status"] == "done"
        mock_queue.pool.enqueue_job.assert_called_once_with("sync_status_to_notion", "goal", str(goal_id))
