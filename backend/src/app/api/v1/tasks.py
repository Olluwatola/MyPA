"""User-facing task CRUD (Feature 1.8) plus the status-only update 1.7's completion sync
hangs off. Tasks are soft-deleted: a deleted task is a 404 on every route here, but its
`notion_block_link` row is kept and Notion is never touched, so the Notion classifier
still treats that line as "already handled" (see decisions-log.md, 2026-09-24).

`status` changes only through `PATCH /tasks/{id}/status` — the one place that enqueues
`sync_status_to_notion`. `PATCH /tasks/{id}` edits content fields and marks each edited
field as a sticky manual override (core/tasks/sticky.py).
"""

import uuid as uuid_pkg
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import BadRequestException, ForbiddenException, NotFoundException
from ...core.tasks.sticky import manual_edit_flags
from ...core.utils import queue
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


@router.post("", response_model=TaskRead, status_code=201)
async def write_task(
    body: TaskCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict:
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
        ),
        schema_to_select=TaskRead,
    )

    if fields_to_guess:
        await queue.pool.enqueue_job("guess_task_fields", str(created["id"]), fields_to_guess)  # type: ignore[union-attr]

    return created


@router.get("", response_model=PaginatedListResponse[TaskRead], status_code=200)
async def read_tasks(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    status: TaskStatus | None = None,
    urgency: Urgency | None = None,
    source: TaskSource | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
) -> dict:
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
    return paginated_response(crud_data=crud_data, page=page, items_per_page=items_per_page)


@router.get("/{task_id}", response_model=TaskRead, status_code=200)
async def read_task(
    task_id: uuid_pkg.UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict:
    return await _get_owned_task(db, task_id, current_user)


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

    changes |= manual_edit_flags(changes)
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
