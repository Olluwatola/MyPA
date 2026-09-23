"""Status-only task update — deliberately narrow, not a general Task CRUD API (out of
scope for this feature). Exists to give completion sync's App -> Notion write-back
direction a genuine caller now (no other task-management endpoint exists yet anywhere in
this codebase to hang it off of) — see `core/notion/completion_sync.py::sync_status_to_notion`.
"""

import uuid as uuid_pkg
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import ForbiddenException, NotFoundException
from ...core.utils import queue
from ...crud.crud_tasks import crud_tasks
from ...schemas.task import TaskRead, TaskStatus
from ..dependencies import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus


@router.patch("/{task_id}/status", response_model=TaskRead, status_code=200)
async def patch_task_status(
    task_id: uuid_pkg.UUID,
    body: TaskStatusUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict:
    task = await crud_tasks.get(db=db, id=task_id)
    if not task:
        raise NotFoundException("Task not found.")
    if task["user_id"] != current_user["id"]:
        raise ForbiddenException("You do not have access to this task.")

    updated = await crud_tasks.update(
        db=db, object={"status": body.status}, id=task_id, schema_to_select=TaskRead
    )

    # Enqueued unconditionally — sync_status_to_notion no-ops on its own if this task
    # isn't Notion-linked, so the caller here doesn't need to know either way.
    await queue.pool.enqueue_job("sync_status_to_notion", "task", str(task_id))  # type: ignore[union-attr]

    return updated
