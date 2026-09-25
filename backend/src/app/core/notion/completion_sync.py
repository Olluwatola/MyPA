"""Bidirectional, check-before-write completion sync between a Notion `to_do` block's
checkbox and its linked Task/Goal status(es). Block-level and all-or-nothing, because
Notion's checkbox is block-level: a block can resolve to multiple items, but it only has
one checkbox (see PRD §6.5) — checked only once EVERY linked item is done, and checking
it directly in Notion marks ALL currently-linked items done. Every write here only fires
when the two sides actually disagree, per the PRD's "no redundant write-back loop" rule.

Goal statuses go beyond done / not done (decisions-log.md 2026-09-24):

| Direction | Rule |
|---|---|
| App -> Notion | A dropped goal is ignored, like a deleted item. A paused goal counts as not done. |
| Notion ticked | Every live item not yet done becomes done — a paused goal included. Dropped is left alone. |
| Notion unticked | Only items that are `done` go back to `open`. Paused and dropped stay as they are. |

The unticked rule matters because `edit_gate.process_changed_block` runs
`sync_checkbox_from_notion` on every processed `to_do` block, even a text-only edit — a
"match the box" rule would flip a paused goal back to open on a typo fix.
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


def _is_live(item: dict[str, Any]) -> bool:
    """Deleted tasks/goals (their link rows are kept) and dropped goals take no part in
    completion sync in either direction."""
    return not item["is_deleted"] and item["status"] != "dropped"


async def determine_desired_checked_state(
    db: AsyncSession, user_id: uuid_pkg.UUID, notion_block_id: str
) -> bool | None:
    """Non-live items are ignored — otherwise one deleted task would stop the block's
    checkbox from ever being checked again. `None` means the block has no live linked
    items, so there is nothing to decide and Notion must not be touched (deleting a task or
    goal never changes Notion)."""
    links = await _linked_items(db, user_id, notion_block_id)

    live_items = []
    for link in links:
        crud = crud_tasks if link["item_type"] == "task" else crud_goals
        item = await crud.get(db=db, id=link["item_id"])
        if item and _is_live(item):
            live_items.append(item)

    if not live_items:
        return None
    return all(item["status"] == "done" for item in live_items)


async def sync_checkbox_from_notion(
    db: AsyncSession, user_id: uuid_pkg.UUID, notion_block_id: str, checked: bool
) -> None:
    """Notion -> App. All-or-nothing across the block's live items: ticked marks every one
    done; unticked reopens only the ones that are done (see the module docstring's table).
    Check-before-write per item. A deleted item or dropped goal is never updated."""
    items = await _linked_items(db, user_id, notion_block_id)
    for link in items:
        crud = crud_tasks if link["item_type"] == "task" else crud_goals
        item = await crud.get(db=db, id=link["item_id"])
        if not item or not _is_live(item):
            continue
        if checked and item["status"] != "done":
            await crud.update(db=db, object={"status": "done"}, id=link["item_id"])
        elif not checked and item["status"] == "done":
            await crud.update(db=db, object={"status": "open"}, id=link["item_id"])


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
