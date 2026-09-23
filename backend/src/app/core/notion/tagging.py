"""Task-id tagging/untagging (PRD §6.5's write path) — built now as a genuine, tested
capability with NO LIVE CALLER yet, since Free-Time Scouring (Feature 1.12) doesn't
exist. Mirrors how Feature 1.6 built `build_inline_keyboard` as a ready primitive with no
consumer at the time.
"""

import uuid as uuid_pkg
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_notion_block_link import crud_notion_block_link
from ...crud.crud_notion_block_sync import crud_notion_block_sync
from ...schemas.notion_block_link import NotionBlockLinkCreate
from ...schemas.notion_block_sync import NotionBlockSyncCreateInternal
from .client import append_block, delete_block, get_block
from .simhash import compute_simhash


async def tag_block(
    db: AsyncSession,
    user_id: uuid_pkg.UUID,
    access_token: str,
    notion_block_id: str,
    item_type: Literal["task", "goal"],
    item_id: uuid_pkg.UUID,
) -> str:
    """Returns the FINAL `notion_block_id` to use going forward — `== notion_block_id`
    unchanged if the block was already a `to_do`; the NEW block's id if it had to be
    converted. Callers MUST persist this: Notion cannot change a block's type in place,
    so converting a plain list item to a `to_do` (so completion sync has a checkbox to
    reconcile against) inserts a brand-new block and archives the original — a real
    identity change, not a cosmetic one."""
    block = await get_block(access_token, notion_block_id)
    final_block_id = notion_block_id

    if block.type != "to_do":
        parent_key = block.parent.get("type")
        parent_id = block.parent.get(parent_key) if parent_key else None
        if not parent_id:
            raise ValueError(f"Could not resolve parent for Notion block {notion_block_id}")

        rich_text = block.raw.get(block.type, {}).get("rich_text", [])
        to_do_payload = {"type": "to_do", "to_do": {"rich_text": rich_text, "checked": False}}
        new_block = await append_block(access_token, parent_id, notion_block_id, to_do_payload)
        await delete_block(access_token, notion_block_id)
        final_block_id = new_block.id

        old_sync = await crud_notion_block_sync.get(db=db, user_id=user_id, notion_block_id=notion_block_id)
        if old_sync:
            await crud_notion_block_sync.db_delete(db=db, id=old_sync["id"], commit=False)
        await crud_notion_block_sync.create(
            db=db,
            object=NotionBlockSyncCreateInternal(
                user_id=user_id,
                notion_block_id=final_block_id,
                notion_page_id=old_sync["notion_page_id"] if old_sync else parent_id,
                last_edited_time=new_block.last_edited_time,
                content_fingerprint=compute_simhash(new_block.plain_text),
            ),
            commit=False,
        )

        # Any OTHER link rows still pointing at the old block id (unlikely but possible
        # if two items were already linked to the same plain-list-item block before this
        # tag call) are re-pointed too, same transaction.
        other_links_result = await crud_notion_block_link.get_multi(
            db=db, user_id=user_id, notion_block_id=notion_block_id
        )
        for other_link in other_links_result["data"]:
            await crud_notion_block_link.db_delete(db=db, id=other_link["id"], commit=False)
            await crud_notion_block_link.create(
                db=db,
                object=NotionBlockLinkCreate(
                    user_id=user_id,
                    notion_block_id=final_block_id,
                    item_type=other_link["item_type"],
                    item_id=other_link["item_id"],
                ),
                commit=False,
            )

    existing_link = await crud_notion_block_link.get(db=db, user_id=user_id, item_type=item_type, item_id=item_id)
    if existing_link:
        await crud_notion_block_link.db_delete(db=db, id=existing_link["id"], commit=False)

    await crud_notion_block_link.create(
        db=db,
        object=NotionBlockLinkCreate(
            user_id=user_id, notion_block_id=final_block_id, item_type=item_type, item_id=item_id
        ),
        commit=False,
    )
    await db.commit()
    return final_block_id


async def untag_block(
    db: AsyncSession, user_id: uuid_pkg.UUID, item_type: Literal["task", "goal"], item_id: uuid_pkg.UUID
) -> None:
    """Deletes only the `NotionBlockLink` row — never touches the Notion block itself
    (no requirement to revert its type; doing so would risk discarding user edits made
    since tagging)."""
    link = await crud_notion_block_link.get(db=db, user_id=user_id, item_type=item_type, item_id=item_id)
    if link:
        await crud_notion_block_link.db_delete(db=db, id=link["id"])
