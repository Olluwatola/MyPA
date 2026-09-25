"""The narrow, Notion-specific "insufficient context" escalation (PRD §5.6 step 6) — a
standalone simple Telegram question, explicitly NOT the general-purpose Interrupt system
(Feature 1.11 doesn't exist yet, and this isn't a first cut of it). Reuses Feature 1.6's
existing outbound-sending job and `build_inline_keyboard` primitive rather than building
anything new for delivery.
"""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from arq import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_goals import crud_goals
from ...crud.crud_notion_block_sync import crud_notion_block_sync
from ...crud.crud_telegram_link import crud_telegram_link
from ...models.notion_block_sync import NotionBlockSync
from ..config import settings
from ..telegram.client import build_inline_keyboard


async def get_oldest_pending_clarification(db: AsyncSession, user_id: uuid_pkg.UUID) -> dict[str, Any] | None:
    """The single correlation mechanism for "which pending question is this reply/tap
    answering" — routes to the OLDEST outstanding clarification for the user. Known,
    stated limitation: if a user has two blocks awaiting clarification simultaneously, a
    reply/tap could resolve the wrong one — mitigated by including the block's own
    summary in the outbound question (self-contextualizing), not fully solved. A per-
    block correlation id is the natural follow-up if this proves confusing in practice."""
    stmt = (
        select(NotionBlockSync)
        .where(NotionBlockSync.user_id == user_id, NotionBlockSync.clarification_requested_at.is_not(None))
        .order_by(NotionBlockSync.clarification_requested_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalars().first()
    if row is None:
        return None
    return {
        "id": row.id,
        "user_id": row.user_id,
        "notion_block_id": row.notion_block_id,
        "notion_page_id": row.notion_page_id,
    }


async def escalate_insufficient_context(
    db: AsyncSession,
    redis: ArqRedis,
    user_id: uuid_pkg.UUID,
    notion_block_sync_id: uuid_pkg.UUID,
    block_summary: str,
) -> None:
    """Always persists the "already asked" flag first, regardless of channel
    availability — this is what stops stage 3 from firing a second clarifying interrupt
    on a later event while one is already outstanding (see PRD §6.5)."""
    await crud_notion_block_sync.update(
        db=db, object={"clarification_requested_at": datetime.now(UTC)}, id=notion_block_sync_id
    )

    link = await crud_telegram_link.get(db=db, user_id=user_id)
    if not link:
        # No channel to ask through yet — no in-app equivalent exists this slice (PRD's
        # own accepted gap). The block stays unresolved until a future event or a
        # Telegram link appears.
        return

    goals_result = await crud_goals.get_multi(
        db=db,
        user_id=user_id,
        status="open",
        is_deleted=False,
        limit=settings.NOTION_CLARIFICATION_CANDIDATE_GOAL_LIMIT,
    )
    candidate_goals: list[dict[str, Any]] = list(goals_result["data"])

    question = (
        f'I found this in your Notion page: "{block_summary}". Which goal does this belong to? '
        "Reply with the goal name, or describe it if it's something new."
    )
    keyboard = (
        build_inline_keyboard([[(goal["title"], f"notion_goal:{goal['id']}") for goal in candidate_goals]])
        if candidate_goals
        else None
    )

    await redis.enqueue_job("send_telegram_message", link["telegram_chat_id"], question, keyboard)
