"""User-facing task CRUD (Feature 1.8) plus the status-only update 1.7's completion sync
hangs off. Tasks are soft-deleted: a deleted task is a 404 on every route here, but its
`notion_block_link` row is kept and Notion is never touched, so the Notion classifier
still treats that line as "already handled" (see decisions-log.md, 2026-09-24).

`status` changes only through `PATCH /tasks/{id}/status` — the one place that enqueues
`sync_status_to_notion`. `PATCH /tasks/{id}` edits content fields and marks each edited
field as a sticky manual override (core/items/sticky.py).

`goal_id` (Feature 1.9) links a task to one of the user's own non-deleted goals, of any
status. A link the user sets or clears is sticky — the AI never changes it.
"""

import uuid as uuid_pkg
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import BadRequestException, ForbiddenException, NotFoundException
from ...core.items.sticky import TASK_STICKY_FLAGS, manual_edit_flags
from ...core.utils import queue
from ...core.utils.etag import with_etag
from ...crud.crud_goals import crud_goals
from ...crud.crud_tasks import crud_tasks
from ...schemas.task import (
    TaskCreate,
    TaskCreateInternal,
    TaskDeletedRead,
    TaskRead,
    TaskSource,
    TaskStatus,
    TaskUpdate,
    Urgency,
)
from ..dependencies import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus


async def _get_owned_task(db: AsyncSession, task_id: uuid_pkg.UUID, current_user: dict) -> dict[str, Any]:
    task = await crud_tasks.get(db=db, id=task_id, is_deleted=False)
    if not task:
        raise NotFoundException("Task not found.")
    if task["user_id"] != current_user["id"]:
        raise ForbiddenException("You do not have access to this task.")
    return task


async def _check_linkable_goal(db: AsyncSession, goal_id: uuid_pkg.UUID, current_user: dict) -> None:
    """The same error whether the goal is missing, deleted, or another user's — never
    reveals whether someone else's goal exists."""
    goal = await crud_goals.get(db=db, id=goal_id, user_id=current_user["id"], is_deleted=False)
    if not goal:
        raise BadRequestException("goal_id does not match any of your goals.")


@router.post("", response_model=TaskRead, status_code=201)
async def write_task(
    body: TaskCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict:
    if body.goal_id is not None:
        await _check_linkable_goal(db, body.goal_id, current_user)

    fields_to_guess = [field for field in ("urgency", "effort_level") if getattr(body, field) is None]

    created = await crud_tasks.create(
        db=db,
        object=TaskCreateInternal(
            user_id=current_user["id"],
            source="manual",
            title=body.title,
            description=body.description,
            due_date=body.due_date,
            urgency=body.urgency or "medium",
            effort_level=body.effort_level,
            # A field the user filled in counts as a manual (sticky) choice; an empty one is
            # left for the background AI guess.
            urgency_manually_set=body.urgency is not None,
            effort_level_manually_set=body.effort_level is not None,
            goal_id=body.goal_id,
            goal_id_manually_set=body.goal_id is not None,
        ),
        schema_to_select=TaskRead,
    )

    if fields_to_guess:
        await queue.pool.enqueue_job("guess_task_fields", str(created["id"]), fields_to_guess)  # type: ignore[union-attr]

    return created


@router.get("", response_model=PaginatedListResponse[TaskRead], status_code=200)
async def read_tasks(
    request: Request,
    response: Response,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    status: TaskStatus | None = None,
    urgency: Urgency | None = None,
    source: TaskSource | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    goal_id: uuid_pkg.UUID | None = None,
) -> dict | Response:
    """Answers `304` when the browser's cached copy is still current (core/utils/etag.py)."""
    if due_from and due_to and due_from > due_to:
        raise BadRequestException("due_from must be on or before due_to.")

    filters: dict[str, Any] = {"user_id": current_user["id"], "is_deleted": False}
    if status:
        filters["status"] = status
    if urgency:
        filters["urgency"] = urgency
    if source:
        filters["source"] = source
    if due_from:
        filters["due_date__gte"] = due_from
    if due_to:
        filters["due_date__lte"] = due_to
    if goal_id:
        # No ownership check needed: the user_id filter already limits this to the
        # caller's own tasks.
        filters["goal_id"] = goal_id

    # Default order: open first, then soonest due date (no date last), then newest, with
    # `id` as a stable tie-breaker. FastCRUD only sorts by plain columns, so this relies on
    # "open" > "done" alphabetically (status desc) and on Postgres putting NULLs last on an
    # ascending sort by default. Revisit if a third status is ever added.
    crud_data = await crud_tasks.get_multi(
        db=db,
        offset=compute_offset(page, items_per_page),
        limit=items_per_page,
        schema_to_select=TaskRead,
        sort_columns=["status", "due_date", "created_at", "id"],
        sort_orders=["desc", "asc", "desc", "desc"],
        **filters,
    )
    payload = paginated_response(crud_data=crud_data, page=page, items_per_page=items_per_page)
    return with_etag(request, response, payload, current_user["id"])


@router.get("/{task_id}", response_model=TaskRead, status_code=200)
async def read_task(
    request: Request,
    response: Response,
    task_id: uuid_pkg.UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict | Response:
    task = await _get_owned_task(db, task_id, current_user)
    return with_etag(request, response, task, current_user["id"])


@router.patch("/{task_id}", response_model=TaskRead, status_code=200)
async def patch_task(
    task_id: uuid_pkg.UUID,
    body: TaskUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any] | TaskRead | None:
    task = await _get_owned_task(db, task_id, current_user)

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return task

    if changes.get("goal_id") is not None:
        await _check_linkable_goal(db, changes["goal_id"], current_user)

    # A goal_id edit (including `null` = unlink) sets goal_id_manually_set here too.
    changes |= manual_edit_flags(changes, TASK_STICKY_FLAGS)
    # return_as_model=True is what makes update() return the row at all — with only
    # schema_to_select it returns None, which fails response validation (a 500).
    updated = await crud_tasks.update(
        db=db, object=changes, id=task_id, is_deleted=False, schema_to_select=TaskRead, return_as_model=True
    )
    return updated


@router.delete("/{task_id}", response_model=TaskDeletedRead, status_code=200)
async def erase_task(
    task_id: uuid_pkg.UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    await _get_owned_task(db, task_id, current_user)

    # Soft delete only. The notion_block_link row is deliberately kept and Notion is never
    # written to — deleting a task never changes Notion.
    await crud_tasks.delete(db=db, id=task_id)
    return {"message": "Task deleted."}


@router.patch("/{task_id}/status", response_model=TaskRead, status_code=200)
async def patch_task_status(
    task_id: uuid_pkg.UUID,
    body: TaskStatusUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> TaskRead | None:
    await _get_owned_task(db, task_id, current_user)

    updated = await crud_tasks.update(
        db=db, object={"status": body.status}, id=task_id, schema_to_select=TaskRead, return_as_model=True
    )

    # Enqueued unconditionally — sync_status_to_notion no-ops on its own if this task
    # isn't Notion-linked, so the caller here doesn't need to know either way.
    await queue.pool.enqueue_job("sync_status_to_notion", "task", str(task_id))  # type: ignore[union-attr]

    return updated
