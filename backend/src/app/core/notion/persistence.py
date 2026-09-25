"""The single write path both Notion classification paths (edit-path per-block
classification and initial-extraction chunked extraction) funnel through, so persistence
logic is never duplicated between them. Deliberately does NOT reuse
`core/llm/extraction.py::run_memory_extraction_pipeline` directly — that function's
single-item, single-outcome interface doesn't fit Notion's multi-item-per-block,
create/update/unlink/link action shape (see the Feature 1.7 planning notes) — but mirrors
its transaction/confidence-gating conventions exactly.
"""

import uuid as uuid_pkg
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_embeddings import crud_embeddings
from ...crud.crud_goals import crud_goals
from ...crud.crud_memory_extraction_records import crud_memory_extraction_records
from ...crud.crud_notion_block_link import crud_notion_block_link
from ...crud.crud_tasks import crud_tasks
from ...schemas.embedding import EmbeddingCreate
from ...schemas.goal import GoalCreateInternal
from ...schemas.memory_extraction_record import MemoryExtractionRecordCreate, MemoryExtractionRecordRead
from ...schemas.notion_block_link import NotionBlockLinkCreate
from ...schemas.task import TaskCreateInternal
from ..config import settings
from ..items.sticky import GOAL_STICKY_FLAGS, TASK_STICKY_FLAGS, drop_sticky_fields
from ..llm.embedding_model import embed_text
from ..logger import logging

logger = logging.getLogger(__name__)


class NotionPersistenceAction(BaseModel):
    kind: Literal["create", "update", "unlink", "link"]
    item_type: Literal["task", "goal"]
    item_id: uuid_pkg.UUID | None = None  # required for update/unlink/link
    title: str | None = None
    description: str | None = None
    due_date: date | None = None
    urgency: Literal["low", "medium", "high"] | None = None
    effort_level: Literal["deep_focus", "light_focus", "passive"] | None = None
    horizon: Literal["short_term", "long_term"] | None = None
    confidence: float | None = None  # required for create — gates against CONFIDENCE_THRESHOLD
    # Task create only: the accepted AI link (core/goals/context.py::resolve_goal_link).
    goal_id: uuid_pkg.UUID | None = None


async def persist_notion_block_outcome(
    db: AsyncSession,
    user_id: uuid_pkg.UUID,
    notion_block_id: str,
    notion_page_id: str,
    block_summary: str,
    actions: list[NotionPersistenceAction],
) -> dict[str, Any]:
    """Always creates one `MemoryExtractionRecord(source_type="notion")` + one embedding
    — mirrors `run_memory_extraction_pipeline`'s always-record behavior, even for a
    not-actionable block (`actions=[]`), so retrieval context stays complete. One
    transaction (`commit=False` throughout, single `db.commit()` at the end); rollback +
    re-raise on any failure, identical shape to the extraction pipeline."""
    try:
        record = await crud_memory_extraction_records.create(
            db=db,
            object=MemoryExtractionRecordCreate(
                user_id=user_id,
                source_type="notion",
                source_channel=None,
                summary=block_summary,
                tasks=[],
            ),
            schema_to_select=MemoryExtractionRecordRead,
            commit=False,
        )

        embedding_vector = await embed_text(block_summary)
        await crud_embeddings.create(
            db=db,
            object=EmbeddingCreate(memory_record_id=record["id"], embedding=embedding_vector),
            commit=False,
        )

        for action in actions:
            if action.kind == "create":
                await _create_item(db, user_id, notion_block_id, record["id"], action)
            elif action.kind == "update":
                await _update_item(db, action)
            elif action.kind == "unlink":
                await _unlink_item(db, user_id, action)
            elif action.kind == "link":
                await _link_existing_item(db, user_id, notion_block_id, action)
    except Exception:
        await db.rollback()
        raise

    await db.commit()
    return record


async def _create_item(
    db: AsyncSession,
    user_id: uuid_pkg.UUID,
    notion_block_id: str,
    memory_record_id: uuid_pkg.UUID,
    action: NotionPersistenceAction,
) -> None:
    """Confidence-gated exactly like `run_memory_extraction_pipeline` — below-threshold
    candidates are silently dropped (they still exist implicitly via the always-created
    memory record's summary, but no Task/Goal/link is created for them)."""
    assert action.confidence is not None, "confidence is required for a 'create' action"
    assert action.title is not None, "title is required for a 'create' action"
    if action.confidence < settings.CONFIDENCE_THRESHOLD:
        return

    if action.item_type == "task":
        created = await crud_tasks.create(
            db=db,
            object=TaskCreateInternal(
                user_id=user_id,
                title=action.title,
                description=action.description,
                due_date=action.due_date,
                urgency=action.urgency or "medium",
                effort_level=action.effort_level,
                source="notion",
                memory_record_id=memory_record_id,
                goal_id=action.goal_id,
            ),
            commit=False,
        )
    else:
        created = await crud_goals.create(
            db=db,
            object=GoalCreateInternal(
                user_id=user_id,
                title=action.title,
                description=action.description,
                # The Notion LLM schema has one date field; for a goal it's the target date
                # (goals have no due_date since 1.9).
                target_date=action.due_date,
                horizon=action.horizon,
                source="notion",
                memory_record_id=memory_record_id,
            ),
            commit=False,
        )

    await crud_notion_block_link.create(
        db=db,
        object=NotionBlockLinkCreate(
            user_id=user_id, notion_block_id=notion_block_id, item_type=action.item_type, item_id=created["id"]
        ),
        commit=False,
    )


async def _update_item(db: AsyncSession, action: NotionPersistenceAction) -> None:
    """Updates the existing Task/Goal in place — no new memory record, no new link row
    (the link already exists and is untouched). A deleted (or missing) task/goal is a
    no-op, and any field the user set by hand (sticky flag) is left alone. Never touches a
    task's `goal_id` — the AI links only when it creates a task."""
    assert action.item_id is not None, "item_id is required for an 'update' action"
    update_fields: dict[str, Any] = {
        key: value
        for key, value in {
            "title": action.title,
            "description": action.description,
            "urgency": action.urgency,
            "effort_level": action.effort_level,
        }.items()
        if value is not None
    }
    if not update_fields:
        return

    if action.item_type == "task":
        crud: Any = crud_tasks
        sticky_flags = TASK_STICKY_FLAGS
    else:
        crud = crud_goals
        sticky_flags = GOAL_STICKY_FLAGS
        # Goal has no urgency/effort_level columns — only title/description apply.
        update_fields = {k: v for k, v in update_fields.items() if k in ("title", "description")}
        if not update_fields:
            return

    # Read without an is_deleted filter so a deleted item is seen (and skipped) rather than
    # hitting update()'s NoResultFound and rolling back the whole block.
    item = await crud.get(db=db, id=action.item_id)
    if not item or item["is_deleted"]:
        return
    fields = drop_sticky_fields(item, update_fields, sticky_flags)
    if fields:
        await crud.update(db=db, object=fields, id=action.item_id, commit=False)


async def _link_existing_item(
    db: AsyncSession, user_id: uuid_pkg.UUID, notion_block_id: str, action: NotionPersistenceAction
) -> None:
    """Links this block to an ALREADY-EXISTING Task/Goal it wasn't previously linked to
    — the "insufficient context, resolved against an existing goal" case (PRD §5.6 step
    6) and the clarification-reply "matched an existing goal" case. No new Task/Goal
    created, no field updates — purely a new `NotionBlockLink` row."""
    assert action.item_id is not None, "item_id is required for a 'link' action"
    existing_link = await crud_notion_block_link.get(
        db=db, user_id=user_id, item_type=action.item_type, item_id=action.item_id
    )
    if existing_link:
        return  # already linked (e.g. to a different block) — nothing to do
    await crud_notion_block_link.create(
        db=db,
        object=NotionBlockLinkCreate(
            user_id=user_id, notion_block_id=notion_block_id, item_type=action.item_type, item_id=action.item_id
        ),
        commit=False,
    )


async def _unlink_item(db: AsyncSession, user_id: uuid_pkg.UUID, action: NotionPersistenceAction) -> None:
    """Deletes only the `NotionBlockLink` row — never the Task/Goal itself (no
    `revoked_at` on this table; the item continues to exist, just no longer tracked
    against this block). Applies to a soft-deleted task's link too: "no longer applies"
    means the line no longer describes it, so nothing is left there to re-create it from."""
    assert action.item_id is not None, "item_id is required for an 'unlink' action"
    link = await crud_notion_block_link.get(db=db, user_id=user_id, item_type=action.item_type, item_id=action.item_id)
    if link:
        await crud_notion_block_link.db_delete(db=db, id=link["id"], commit=False)
