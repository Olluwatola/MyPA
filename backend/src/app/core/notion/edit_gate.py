"""The edit-path 3-stage gate (PRD §6.5) — the orchestrator both
`core/notion/jobs.py::process_notion_content_updated` (real webhook events) and
`reconcile_notion_pages` (fallback reconciliation, replaying every block as a synthetic
"content_updated") call, per block, so both paths share identical gate/classification
behavior rather than duplicating it.
"""

import uuid as uuid_pkg
from typing import Any

from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_goals import crud_goals
from ...crud.crud_notion_block_link import crud_notion_block_link
from ...crud.crud_notion_block_sync import crud_notion_block_sync
from ...crud.crud_tasks import crud_tasks
from ...schemas.notion_block_sync import NotionBlockSyncCreateInternal
from ...schemas.notion_classification import NotionExtractedItem
from ..config import settings
from ..goals.context import load_open_goals, resolve_goal_link
from ..llm.notion_classification import classify_fresh_block, reclassify_anchored_block
from .clarification import escalate_insufficient_context
from .client import NotionBlock
from .completion_sync import sync_checkbox_from_notion
from .goal_resolution import resolve_against_existing_goals
from .persistence import NotionPersistenceAction, persist_notion_block_outcome
from .simhash import compute_simhash, hamming_distance


def _item_to_create_action(item: NotionExtractedItem, open_goals: list[dict[str, Any]]) -> NotionPersistenceAction:
    """Only a task gets an AI goal link, and only when the LLM is confident
    (core/goals/context.py::resolve_goal_link)."""
    return NotionPersistenceAction(
        kind="create",
        item_type=item.item_type,
        title=item.title,
        description=item.description,
        due_date=item.due_date,
        urgency=item.urgency,
        effort_level=item.effort_level,
        horizon=item.horizon,
        confidence=item.confidence,
        goal_id=(
            resolve_goal_link(item.goal_ref, item.goal_link_confidence, open_goals)
            if item.item_type == "task"
            else None
        ),
    )


def _render_full_page_text(full_page_blocks: list[NotionBlock]) -> str:
    return "\n".join(block.plain_text for block in full_page_blocks if block.plain_text)


async def _existing_links(db: AsyncSession, user_id: uuid_pkg.UUID, notion_block_id: str) -> list[dict[str, Any]]:
    result = await crud_notion_block_link.get_multi(db=db, user_id=user_id, notion_block_id=notion_block_id)
    return list(result["data"])


async def _existing_items_for_prompt(db: AsyncSession, links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Soft-deleted tasks and goals are included on purpose, exactly like live ones and
    with no "deleted" marker: the classifier must still see the item as already handled for
    this line, or it would re-create it. A genuinely new item on the same line still comes
    back as an additional item and is created; an update aimed at the deleted item is a
    no-op in `persistence._update_item`."""
    items = []
    for link in links:
        crud = crud_tasks if link["item_type"] == "task" else crud_goals
        item = await crud.get(db=db, id=link["item_id"])  # no is_deleted filter — see docstring
        if item:
            items.append(
                {
                    "item_id": str(link["item_id"]),
                    "item_type": link["item_type"],
                    "title": item["title"],
                    "description": item.get("description"),
                }
            )
    return items


async def _handle_fresh_classification(
    db: AsyncSession,
    redis: ArqRedis,
    user_id: uuid_pkg.UUID,
    notion_block_id: str,
    notion_page_id: str,
    notion_block_sync_id: uuid_pkg.UUID,
    full_page_text: str,
    target_block: NotionBlock,
) -> None:
    open_goals = await load_open_goals(db, user_id)
    result = await classify_fresh_block(full_page_text, target_block, open_goals)

    if result.outcome == "not_actionable":
        await persist_notion_block_outcome(db, user_id, notion_block_id, notion_page_id, result.summary, [])
        return

    if result.outcome == "actionable":
        actions = [_item_to_create_action(item, open_goals) for item in result.items]
        await persist_notion_block_outcome(db, user_id, notion_block_id, notion_page_id, result.summary, actions)
        return

    # insufficient_context
    resolved_goal_id = await resolve_against_existing_goals(db, user_id, result.summary)
    if resolved_goal_id is not None:
        actions = [NotionPersistenceAction(kind="link", item_type="goal", item_id=resolved_goal_id)]
        await persist_notion_block_outcome(db, user_id, notion_block_id, notion_page_id, result.summary, actions)
        return

    await escalate_insufficient_context(db, redis, user_id, notion_block_sync_id, result.summary)


async def _handle_anchored_classification(
    db: AsyncSession,
    redis: ArqRedis,
    user_id: uuid_pkg.UUID,
    notion_block_id: str,
    notion_page_id: str,
    notion_block_sync_id: uuid_pkg.UUID,
    full_page_text: str,
    target_block: NotionBlock,
    existing_links: list[dict[str, Any]],
) -> None:
    existing_items = await _existing_items_for_prompt(db, existing_links)
    open_goals = await load_open_goals(db, user_id)
    result = await reclassify_anchored_block(full_page_text, target_block, existing_items, open_goals)

    actions: list[NotionPersistenceAction] = []
    for outcome in result.existing_items:
        if outcome.disposition == "unchanged":
            continue
        if outcome.disposition == "updated":
            actions.append(
                NotionPersistenceAction(
                    kind="update",
                    item_type=next(
                        (link["item_type"] for link in existing_links if link["item_id"] == outcome.item_id), "task"
                    ),
                    item_id=outcome.item_id,
                    title=outcome.updated_title,
                    description=outcome.updated_description,
                    urgency=outcome.updated_urgency,
                    effort_level=outcome.updated_effort_level,
                )
            )
        elif outcome.disposition == "no_longer_applies":
            actions.append(
                NotionPersistenceAction(
                    kind="unlink",
                    item_type=next(
                        (link["item_type"] for link in existing_links if link["item_id"] == outcome.item_id), "task"
                    ),
                    item_id=outcome.item_id,
                )
            )

    # Links are only ever made on create — an "updated" outcome above never carries goal_id.
    actions.extend(_item_to_create_action(item, open_goals) for item in result.additional_items)

    await persist_notion_block_outcome(db, user_id, notion_block_id, notion_page_id, result.summary, actions)

    if result.insufficient_context:
        resolved_goal_id = await resolve_against_existing_goals(db, user_id, result.summary)
        if resolved_goal_id is None:
            await escalate_insufficient_context(db, redis, user_id, notion_block_sync_id, result.summary)


async def process_changed_block(
    db: AsyncSession,
    redis: ArqRedis,
    user_id: uuid_pkg.UUID,
    notion_page_id: str,
    block_id: str,
    full_page_blocks: list[NotionBlock],
) -> None:
    """One call per changed block — never batched (a deliberate, confirmed override of
    PRD §6.5 stage 4, see decisions-log.md 2026-09-23)."""
    target_block = next((block for block in full_page_blocks if block.id == block_id), None)
    if target_block is None:
        # Block no longer on the page (deleted/moved out from under us between the
        # webhook firing and this fetch) — nothing to gate against.
        return

    # Stage 0 — checkbox sync is independent of stages 1-3: a pure checkbox toggle must
    # sync even if the text is byte-identical (stage 2 would otherwise correctly no-op
    # the text path and never reach this).
    if target_block.type == "to_do":
        checked = bool(target_block.raw.get("to_do", {}).get("checked", False))
        await sync_checkbox_from_notion(db, user_id, block_id, checked)

    existing_sync = await crud_notion_block_sync.get(db=db, user_id=user_id, notion_block_id=block_id)

    # Stage 1 — timestamp check.
    if existing_sync is not None and existing_sync["last_edited_time"] == target_block.last_edited_time:
        return

    # Stage 2 — fingerprint check (only for a block we've seen before; a brand-new
    # watermark row always proceeds to classification since there's nothing to compare
    # against yet).
    fingerprint = compute_simhash(target_block.plain_text)
    if existing_sync is not None:
        distance = hamming_distance(existing_sync["content_fingerprint"], fingerprint)
        if distance <= settings.NOTION_EDIT_SIMHASH_UNCHANGED_THRESHOLD:
            await crud_notion_block_sync.update(
                db=db,
                object={"last_edited_time": target_block.last_edited_time, "content_fingerprint": fingerprint},
                id=existing_sync["id"],
            )
            return

    # Stage 3 — classification, always with full-page context.
    full_page_text = _render_full_page_text(full_page_blocks)
    existing_links = await _existing_links(db, user_id, block_id)

    if existing_sync is not None:
        sync_id = existing_sync["id"]
        await crud_notion_block_sync.update(
            db=db,
            object={"last_edited_time": target_block.last_edited_time, "content_fingerprint": fingerprint},
            id=sync_id,
        )
    else:
        created_sync = await crud_notion_block_sync.create(
            db=db,
            object=NotionBlockSyncCreateInternal(
                user_id=user_id,
                notion_block_id=block_id,
                notion_page_id=notion_page_id,
                last_edited_time=target_block.last_edited_time,
                content_fingerprint=fingerprint,
            ),
        )
        sync_id = created_sync["id"]

    if not existing_links:
        await _handle_fresh_classification(
            db, redis, user_id, block_id, notion_page_id, sync_id, full_page_text, target_block
        )
    else:
        await _handle_anchored_classification(
            db, redis, user_id, block_id, notion_page_id, sync_id, full_page_text, target_block, existing_links
        )
