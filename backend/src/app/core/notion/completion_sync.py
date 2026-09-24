"""Bidirectional, check-before-write completion sync between a Notion `to_do` block's
checkbox and its linked Task/Goal status(es). Block-level and all-or-nothing, because
Notion's checkbox is block-level: a block can resolve to multiple items, but it only has
one checkbox (see PRD §6.5) — checked only once EVERY linked item is done, and checking
it directly in Notion marks ALL currently-linked items done. Every write here only fires
when the two sides actually disagree, per the PRD's "no redundant write-back loop" rule.
"""

import uuid as uuid_pkg
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_goals import crud_goals
from ...crud.crud_notion_block_link import crud_notion_block_link
from ...crud.crud_notion_connection import crud_notion_connection
from ...crud.crud_tasks import crud_tasks
from ..crypto import decrypt_token
from ..db.database import local_session
from .client import get_block, update_block_checkbox


async def _linked_items(db: AsyncSession, user_id: uuid_pkg.UUID, notion_block_id: str) -> list[dict[str, Any]]:
    result = await crud_notion_block_link.get_multi(db=db, user_id=user_id, notion_block_id=notion_block_id)
    return list(result["data"])


async def determine_desired_checked_state(
    db: AsyncSession, user_id: uuid_pkg.UUID, notion_block_id: str
) -> bool | None:
    """Soft-deleted tasks (their link rows are kept) are ignored — otherwise one deleted
    task would stop the block's checkbox from ever being checked again. `None` means the
    block has no live linked items, so there is nothing to decide and Notion must not be
    touched (deleting a task never changes Notion)."""
    links = await _linked_items(db, user_id, notion_block_id)

    live_items = []
    for link in links:
        crud = crud_tasks if link["item_type"] == "task" else crud_goals
        item = await crud.get(db=db, id=link["item_id"])
        if item and not item.get("is_deleted"):  # goal rows have no is_deleted key
            live_items.append(item)

    if not live_items:
        return None
    return all(item["status"] == "done" for item in live_items)


async def sync_checkbox_from_notion(
    db: AsyncSession, user_id: uuid_pkg.UUID, notion_block_id: str, checked: bool
) -> None:
    """Notion -> App. All-or-nothing: every linked item for this block gets its
    status set to match `checked`. Check-before-write per item (skips any item already in
    the desired status). A soft-deleted task is never revived or updated."""
    desired_status: Literal["open", "done"] = "done" if checked else "open"

    items = await _linked_items(db, user_id, notion_block_id)
    for link in items:
        crud = crud_tasks if link["item_type"] == "task" else crud_goals
        item = await crud.get(db=db, id=link["item_id"])
        if item and not item.get("is_deleted") and item["status"] != desired_status:
            await crud.update(db=db, object={"status": desired_status}, id=link["item_id"])


async def sync_status_to_notion(ctx: dict[str, Any], item_type: Literal["task", "goal"], item_id: str) -> None:
    """App -> Notion. No `NotionBlockLink` for `(item_type, item_id)` -> no-op (item
    isn't Notion-linked). Otherwise: compute the desired checkbox state, fetch the
    block's CURRENT checked state (check-before-write), and only write if it differs."""
    async with local_session() as db:
        link = await crud_notion_block_link.get(db=db, item_type=item_type, item_id=uuid_pkg.UUID(item_id))
        if not link:
            return

        connection = await crud_notion_connection.get(db=db, user_id=link["user_id"], revoked_at=None)
        if not connection:
            return
        access_token = decrypt_token(connection["access_token"])

        desired_checked = await determine_desired_checked_state(db, link["user_id"], link["notion_block_id"])
        if desired_checked is None:
            return
        current_block = await get_block(access_token, link["notion_block_id"])
        current_checked = bool(current_block.raw.get("to_do", {}).get("checked", False))
        if current_checked != desired_checked:
            await update_block_checkbox(access_token, link["notion_block_id"], desired_checked)
