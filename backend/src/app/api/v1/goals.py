"""User-facing goal CRUD (Feature 1.9) plus the status-only update 1.7's completion sync
hangs off — mirrors `api/v1/tasks.py`. Goals are soft-deleted: a deleted goal is a 404 on
every route here, but its `notion_block_link` row is kept and Notion is never touched, so
the Notion classifier still treats that line as "already handled" (decisions-log.md,
2026-09-24). Deleting a goal also clears `goal_id` on the tasks linked to it.

`status` changes only through `PATCH /goals/{id}/status` — the one place that enqueues
`sync_status_to_notion`. `PATCH /goals/{id}` edits content fields and marks an edited
title/description as a sticky manual override (core/items/sticky.py).
"""

import uuid as uuid_pkg
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import ForbiddenException, NotFoundException
from ...core.items.sticky import GOAL_STICKY_FLAGS, manual_edit_flags
from ...core.utils import queue
from ...core.utils.etag import with_etag
from ...crud.crud_goals import crud_goals
from ...models.task import Task
from ...schemas.goal import (
    GoalCreate,
    GoalCreateInternal,
    GoalDeletedRead,
    GoalHorizon,
    GoalRead,
    GoalSource,
    GoalStatus,
    GoalUpdate,
)
from ..dependencies import get_current_user

router = APIRouter(prefix="/goals", tags=["goals"])


class GoalStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: GoalStatus


async def _get_owned_goal(db: AsyncSession, goal_id: uuid_pkg.UUID, current_user: dict) -> dict[str, Any]:
    goal = await crud_goals.get(db=db, id=goal_id, is_deleted=False)
    if not goal:
        raise NotFoundException("Goal not found.")
    if goal["user_id"] != current_user["id"]:
        raise ForbiddenException("You do not have access to this goal.")
    return goal


@router.post("", response_model=GoalRead, status_code=201)
async def write_goal(
    body: GoalCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict:
    created = await crud_goals.create(
        db=db,
        object=GoalCreateInternal(
            user_id=current_user["id"],
            source="manual",
            title=body.title,
            description=body.description,
            horizon=body.horizon,
            target_date=body.target_date,
        ),
        schema_to_select=GoalRead,
    )

    # An empty horizon is guessed by the AI in the background; stays empty if that fails.
    if body.horizon is None:
        await queue.pool.enqueue_job("guess_goal_horizon", str(created["id"]))  # type: ignore[union-attr]

    return created


@router.get("", response_model=PaginatedListResponse[GoalRead], status_code=200)
async def read_goals(
    request: Request,
    response: Response,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[list[GoalStatus] | None, Query()] = None,
    horizon: GoalHorizon | None = None,
    source: GoalSource | None = None,
) -> dict | Response:
    """`status` takes several values (`?status=open&status=paused` for an "active goals"
    view). Newest first — the tasks list's "open first" trick relies on the alphabetical
    order of two statuses and doesn't work with four. Answers `304` when the browser's
    cached copy is still current (core/utils/etag.py)."""
    filters: dict[str, Any] = {"user_id": current_user["id"], "is_deleted": False}
    if status:
        filters["status__in"] = status
    if horizon:
        filters["horizon"] = horizon
    if source:
        filters["source"] = source

    crud_data = await crud_goals.get_multi(
        db=db,
        offset=compute_offset(page, items_per_page),
        limit=items_per_page,
        schema_to_select=GoalRead,
        sort_columns=["created_at", "id"],
        sort_orders=["desc", "desc"],
        **filters,
    )
    payload = paginated_response(crud_data=crud_data, page=page, items_per_page=items_per_page)
    return with_etag(request, response, payload, current_user["id"])


@router.get("/{goal_id}", response_model=GoalRead, status_code=200)
async def read_goal(
    request: Request,
    response: Response,
    goal_id: uuid_pkg.UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict | Response:
    goal = await _get_owned_goal(db, goal_id, current_user)
    return with_etag(request, response, goal, current_user["id"])


@router.patch("/{goal_id}", response_model=GoalRead, status_code=200)
async def patch_goal(
    goal_id: uuid_pkg.UUID,
    body: GoalUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any] | GoalRead | None:
    goal = await _get_owned_goal(db, goal_id, current_user)

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return goal

    changes |= manual_edit_flags(changes, GOAL_STICKY_FLAGS)
    # return_as_model=True is what makes update() return the row at all — with only
    # schema_to_select it returns None, which fails response validation (a 500).
    updated = await crud_goals.update(
        db=db, object=changes, id=goal_id, is_deleted=False, schema_to_select=GoalRead, return_as_model=True
    )
    return updated


@router.delete("/{goal_id}", response_model=GoalDeletedRead, status_code=200)
async def erase_goal(
    goal_id: uuid_pkg.UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    await _get_owned_goal(db, goal_id, current_user)

    # Soft delete doesn't fire the FK's ON DELETE SET NULL, so tasks linked to this goal
    # are un-linked here. Plain SQLAlchemy, not FastCRUD: FastCRUD's update raises when
    # 0 rows match, and a goal with no tasks is normal. Committed together with the soft
    # delete below (same session).
    await db.execute(update(Task).where(Task.goal_id == goal_id).values(goal_id=None))

    # Soft delete only. The notion_block_link row is deliberately kept and Notion is never
    # written to — deleting a goal never changes Notion.
    await crud_goals.delete(db=db, id=goal_id)
    return {"message": "Goal deleted."}


@router.patch("/{goal_id}/status", response_model=GoalRead, status_code=200)
async def patch_goal_status(
    goal_id: uuid_pkg.UUID,
    body: GoalStatusUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> GoalRead | None:
    await _get_owned_goal(db, goal_id, current_user)

    # return_as_model=True fixes D-06: without it update() returns None and this route 500s
    # after the write has already happened.
    updated = await crud_goals.update(
        db=db, object={"status": body.status}, id=goal_id, schema_to_select=GoalRead, return_as_model=True
    )

    # Enqueued unconditionally — sync_status_to_notion no-ops on its own if this goal
    # isn't Notion-linked, so the caller here doesn't need to know either way.
    await queue.pool.enqueue_job("sync_status_to_notion", "goal", str(goal_id))  # type: ignore[union-attr]

    return updated
