"""Unit tests for the status-only task update endpoint — deliberately narrow (see
api/v1/tasks.py's docstring for why it exists): ownership enforcement, status update, and
`sync_status_to_notion` enqueued unconditionally (the job itself no-ops if unlinked)."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.api.v1.tasks import TaskStatusUpdate, patch_task_status
from src.app.core.exceptions.http_exceptions import ForbiddenException, NotFoundException

MODULE = "src.app.api.v1.tasks"


class TestPatchTaskStatus:
    @pytest.mark.asyncio
    async def test_missing_task_raises_not_found(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundException):
                await patch_task_status(
                    task_id=uuid7(),
                    body=TaskStatusUpdate(status="done"),
                    current_user=current_user_dict,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_other_users_task_raises_forbidden(self, mock_db, current_user_dict):
        task = {"user_id": uuid7(), "status": "open"}  # not current_user's id
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=task)
            with pytest.raises(ForbiddenException):
                await patch_task_status(
                    task_id=uuid7(),
                    body=TaskStatusUpdate(status="done"),
                    current_user=current_user_dict,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_updates_status_and_enqueues_notion_sync_unconditionally(self, mock_db, current_user_dict):
        task_id = uuid7()
        task = {"user_id": current_user_dict["id"], "status": "open"}
        with (
            patch(f"{MODULE}.crud_tasks") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(return_value={"status": "done"})
            mock_queue.pool.enqueue_job = AsyncMock()

            result = await patch_task_status(
                task_id=task_id, body=TaskStatusUpdate(status="done"), current_user=current_user_dict, db=mock_db
            )

        assert result["status"] == "done"
        mock_queue.pool.enqueue_job.assert_called_once_with("sync_status_to_notion", "task", str(task_id))
