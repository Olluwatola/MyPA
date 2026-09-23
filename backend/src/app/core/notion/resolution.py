"""Resolves which user a Notion page belongs to — needed because the webhook receiver
never touches the DB, and a page id alone doesn't say whose connection it belongs to."""

import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_notion_connection import crud_notion_connection
from ...crud.crud_notion_shared_page import crud_notion_shared_page
from ...schemas.notion_shared_page import NotionSharedPageCreateInternal
from ..crypto import decrypt_token
from ..logger import logging
from .client import get_page_parent

logger = logging.getLogger(__name__)


async def resolve_user_for_page(db: AsyncSession, page_id: str) -> tuple[uuid_pkg.UUID, str] | None:
    """Returns `(user_id, decrypted_access_token)` for `page_id`, or `None` if it can't
    be resolved.

    1. Direct hit: a non-revoked `notion_shared_page` row for `page_id`.
    2. Miss (a newly-cascaded sub-page — access to it cascades from a shared ancestor
       before its own grant row exists): walk up via `get_page_parent`, using any
       non-revoked connection's token to make the lookup call, until a parent hits
       `notion_shared_page` or a `workspace`-level parent is reached (dead end). On
       success, auto-registers the sub-page so future events resolve via step 1
       directly. This is a rare defensive fallback — in practice a new sub-page's own
       `page.created` event resolves via step 1 almost always, since MyPA itself learns
       of it (and could register it) at that point."""
    direct = await crud_notion_shared_page.get(db=db, notion_page_id=page_id, revoked_at=None)
    if direct:
        connection = await crud_notion_connection.get(db=db, user_id=direct["user_id"], revoked_at=None)
        if connection:
            return direct["user_id"], decrypt_token(connection["access_token"])
        return None

    return await _resolve_via_parent_walk(db, page_id)


async def _resolve_via_parent_walk(db: AsyncSession, page_id: str) -> tuple[uuid_pkg.UUID, str] | None:
    connections_result = await crud_notion_connection.get_multi(db=db, revoked_at=None)
    connections = list(connections_result["data"])
    if not connections:
        return None

    # Single-tenant-per-workspace is the common case for this MVP — trying the
    # most-recently-connected user first is a stated, reasonable heuristic for this
    # rare-path fallback, not the primary resolution mechanism.
    for connection in connections:
        access_token = decrypt_token(connection["access_token"])
        current_page_id = page_id
        for _ in range(10):  # bounded walk — a real page tree is never this deep
            parent = await get_page_parent(access_token, current_page_id)
            if parent is None:
                break
            parent_type = parent.get("type")
            if parent_type == "workspace":
                break
            parent_id = parent.get(parent_type)
            if not parent_id:
                break
            existing = await crud_notion_shared_page.get(
                db=db, user_id=connection["user_id"], notion_page_id=parent_id, revoked_at=None
            )
            if existing:
                await crud_notion_shared_page.create(
                    db=db,
                    object=NotionSharedPageCreateInternal(
                        user_id=connection["user_id"], notion_page_id=page_id, granted_at=datetime.now(UTC)
                    ),
                )
                return connection["user_id"], access_token
            current_page_id = parent_id

    return None
