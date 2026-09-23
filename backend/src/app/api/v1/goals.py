"""Status-only goal update — mirrors `api/v1/tasks.py`'s shape exactly; see its
docstring for why this narrow endpoint exists."""

import uuid as uuid_pkg
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import ForbiddenException, NotFoundException
from ...core.utils import queue
from ...crud.crud_goals import crud_goals
from ...schemas.goal import GoalRead, GoalStatus
from ..dependencies import get_current_user

router = APIRouter(prefix="/goals", tags=["goals"])


class GoalStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: GoalStatus


@router.patch("/{goal_id}/status", response_model=GoalRead, status_code=200)
async def patch_goal_status(
    goal_id: uuid_pkg.UUID,
    body: GoalStatusUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict:
    goal = await crud_goals.get(db=db, id=goal_id)
    if not goal:
        raise NotFoundException("Goal not found.")
    if goal["user_id"] != current_user["id"]:
        raise ForbiddenException("You do not have access to this goal.")

    updated = await crud_goals.update(
        db=db, object={"status": body.status}, id=goal_id, schema_to_select=GoalRead
    )

    await queue.pool.enqueue_job("sync_status_to_notion", "goal", str(goal_id))  # type: ignore[union-attr]

    return updated
