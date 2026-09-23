"""ARQ job functions for the Notion channel — registered on `core/worker.py`'s
`WorkerSettings`. Every job opens its own DB session via `local_session()`, same
convention as `core/integrations/jobs.py`/`core/telegram/jobs.py`. `_retry_delay_seconds`
is imported rather than redefined — matches `core/telegram/jobs.py`'s own precedent."""

import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import Retry
from sqlalchemy import or_, select

from ...crud.crud_notion_connection import crud_notion_connection
from ...crud.crud_notion_shared_page import crud_notion_shared_page
from ...models.conversation_message import ConversationMessage
from ...models.goal import Goal
from ...models.task import Task
from ...schemas.notion_shared_page import NotionSharedPageCreateInternal
from ..config import settings
from ..crypto import decrypt_token
from ..db.database import local_session
from ..integrations.jobs import _retry_delay_seconds
from ..logger import logging
from .client import fetch_all_blocks_recursive, search_accessible_pages
from .edit_gate import process_changed_block
from .initial_extraction import run_initial_extraction
from .resolution import resolve_user_for_page

logger = logging.getLogger(__name__)


async def run_notion_initial_extraction(ctx: dict[str, Any], page_id: str) -> None:
    async with local_session() as db:
        resolved = await resolve_user_for_page(db, page_id)
        if resolved is None:
            logger.warning(f"Could not resolve a user for Notion page {page_id}, skipping.")
            return
        user_id, access_token = resolved

        try:
            await run_initial_extraction(db, user_id, access_token, page_id)
        except Exception as exc:
            logger.exception(f"run_notion_initial_extraction failed for page {page_id}")
            raise Retry(defer=_retry_delay_seconds(ctx.get("job_try", 1))) from exc


async def process_notion_content_updated(ctx: dict[str, Any], page_id: str, updated_block_ids: list[str]) -> None:
    async with local_session() as db:
        resolved = await resolve_user_for_page(db, page_id)
        if resolved is None:
            logger.warning(f"Could not resolve a user for Notion page {page_id}, skipping.")
            return
        user_id, access_token = resolved

        try:
            full_page_blocks = await fetch_all_blocks_recursive(access_token, page_id)
        except Exception as exc:
            logger.exception(f"Failed to fetch blocks for Notion page {page_id}")
            raise Retry(defer=_retry_delay_seconds(ctx.get("job_try", 1))) from exc

        redis = ctx["redis"]
        for block_id in updated_block_ids:
            try:
                await process_changed_block(db, redis, user_id, page_id, block_id, full_page_blocks)
            except Exception:
                logger.exception(f"Failed to process changed Notion block {block_id} on page {page_id}")
                continue


async def _active_notion_user_ids(db: Any, window_days: int) -> set[uuid_pkg.UUID]:
    """A user counts as active if they have a `ConversationMessage`, `Task`, or `Goal`
    with a recent `created_at`/`updated_at` within `window_days` — a new, explicitly-
    stated definition (no existing "last active" concept in this codebase to reuse).
    Deliberately generous (any of three tables): under-counting here means a real edit
    goes un-reconciled up to `window_days` late, an acceptable failure mode for a stated
    temporary substitute for the PRD's real JIT-before-briefing/Scouring trigger."""
    threshold = datetime.now(UTC) - timedelta(days=window_days)

    conversation_ids = select(ConversationMessage.user_id).where(ConversationMessage.created_at >= threshold)
    task_ids = select(Task.user_id).where(or_(Task.created_at >= threshold, Task.updated_at >= threshold))
    goal_ids = select(Goal.user_id).where(or_(Goal.created_at >= threshold, Goal.updated_at >= threshold))

    active: set[uuid_pkg.UUID] = set()
    for stmt in (conversation_ids, task_ids, goal_ids):
        result = await db.execute(stmt)
        active.update(result.scalars().all())
    return active


async def reconcile_notion_pages(ctx: dict[str, Any]) -> None:
    """Cron, daily. A deliberate, temporary substitute for the PRD's actual
    just-in-time-before-briefing/Scouring trigger (neither feature exists yet) — revisit
    once they do, at which point reconciliation should likely become on-demand rather
    than a blind daily sweep. Gated by the 30-day (default) active-user window so a
    dormant tenant costs nothing."""
    redis = ctx["redis"]
    async with local_session() as db:
        active_user_ids = await _active_notion_user_ids(db, settings.NOTION_RECONCILIATION_ACTIVE_WINDOW_DAYS)
        if not active_user_ids:
            return

        connections_result = await crud_notion_connection.get_multi(db=db, revoked_at=None)
        for connection in connections_result["data"]:
            if connection["user_id"] not in active_user_ids:
                continue
            try:
                await _reconcile_one_user(db, redis, connection)
            except Exception:
                logger.exception(f"Notion reconciliation failed for connection {connection['id']}")
                continue


async def _reconcile_one_user(db: Any, redis: Any, connection: dict[str, Any]) -> None:
    access_token = decrypt_token(connection["access_token"])
    user_id = connection["user_id"]

    live_pages = await search_accessible_pages(access_token)
    live_page_ids = {page["id"] for page in live_pages}

    tracked_result = await crud_notion_shared_page.get_multi(db=db, user_id=user_id, revoked_at=None)
    tracked_pages = tracked_result["data"]
    for tracked in tracked_pages:
        if tracked["notion_page_id"] not in live_page_ids:
            # This is the ONLY place page-unshare is ever detected — Notion sends no
            # webhook for it.
            await crud_notion_shared_page.update(db=db, object={"revoked_at": datetime.now(UTC)}, id=tracked["id"])

    tracked_page_ids = {tracked["notion_page_id"] for tracked in tracked_pages}
    for page_id in live_page_ids - tracked_page_ids:
        await crud_notion_shared_page.create(
            db=db,
            object=NotionSharedPageCreateInternal(
                user_id=user_id, notion_page_id=page_id, granted_at=datetime.now(UTC)
            ),
        )

    for page_id in live_page_ids:
        try:
            full_page_blocks = await fetch_all_blocks_recursive(access_token, page_id)
        except Exception:
            logger.exception(f"Reconciliation: failed to fetch blocks for page {page_id}")
            continue

        for block in full_page_blocks:
            try:
                await process_changed_block(db, redis, user_id, page_id, block.id, full_page_blocks)
            except Exception:
                logger.exception(f"Reconciliation: failed to process block {block.id} on page {page_id}")
                continue
