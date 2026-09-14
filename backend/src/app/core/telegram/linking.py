"""Redis-backed one-time linking token, plus the `TelegramLink` upsert logic itself — both
live here (not in `api/v1/webhooks_telegram.py`) per this codebase's convention of keeping
business logic in `core/`, not the route handler that happens to receive the trigger for it.

The token part uses `core/utils/cache.py`'s `client` global (not ARQ's `queue.pool`, a
deliberate separation between cache and queue connections). No encryption on the stored
value — the token is opaque, single-use, short-lived; Redis itself is the trust boundary
here, matching the ERD's own Redis-not-Postgres reasoning for this token.
"""

import secrets
import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_telegram_link import crud_telegram_link
from ...schemas.telegram_link import TelegramLinkCreateInternal
from ..config import settings
from ..utils import cache

LINK_TOKEN_KEY_PREFIX = "telegram_link_token"


def _token_key(token: str) -> str:
    return f"{LINK_TOKEN_KEY_PREFIX}:{token}"


async def create_link_token(user_id: uuid_pkg.UUID) -> str:
    assert cache.client is not None, "Redis cache client not initialized."
    token = secrets.token_urlsafe(32)
    await cache.client.set(_token_key(token), str(user_id), ex=settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS)
    return token


async def consume_link_token(token: str) -> uuid_pkg.UUID | None:
    """Atomic fetch-and-delete (`GETDEL`) — avoids a race where two concurrent `/start`
    calls both succeed against the same token."""
    assert cache.client is not None, "Redis cache client not initialized."
    raw_user_id = await cache.client.getdel(_token_key(token))
    if raw_user_id is None:
        return None
    value = raw_user_id.decode() if isinstance(raw_user_id, bytes) else raw_user_id
    return uuid_pkg.UUID(value)


def build_telegram_deep_link(token: str) -> str:
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"


async def link_telegram_chat(db: AsyncSession, user_id: uuid_pkg.UUID, chat_id: int) -> None:
    """Upserts the `TelegramLink` row for `user_id`, pointed at `chat_id`. Handles both
    re-link cases the same way — most-recent-link-wins — a minimal, non-crashing
    resolution of the PRD's own acknowledged-unresolved Telegram identity edge cases
    (§11: "what happens if a user re-links a different Telegram account... needs
    explicit UX, not just backend handling"), not a full resolution of that UX gap.

    Order matters: any OTHER user's stale row on this exact `chat_id` is cleared first,
    unconditionally, before touching this user's own row — `telegram_chat_id` has a
    DB-level unique constraint, so linking this chat to `user_id` while a different
    user's row still claims it would otherwise raise an unhandled `IntegrityError`
    (this was a real bug in an earlier version of this function that only cleared the
    stale row on the create path, not the update path)."""
    linked_at = datetime.now(UTC)

    stale_by_chat = await crud_telegram_link.get(db=db, telegram_chat_id=chat_id)
    if stale_by_chat and stale_by_chat["user_id"] != user_id:
        await crud_telegram_link.db_delete(db=db, id=stale_by_chat["id"])

    existing_by_user = await crud_telegram_link.get(db=db, user_id=user_id)
    if existing_by_user:
        await crud_telegram_link.update(
            db=db, object={"telegram_chat_id": chat_id, "linked_at": linked_at}, id=existing_by_user["id"]
        )
    else:
        await crud_telegram_link.create(
            db=db, object=TelegramLinkCreateInternal(user_id=user_id, telegram_chat_id=chat_id, linked_at=linked_at)
        )
