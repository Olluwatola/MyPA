"""Minimal per-chat abuse rate-limiting (PRD §11) — a fixed-window Redis counter, not a
general-purpose rate-limiting framework (none exists in this codebase; Slice 1 stripped
the template's tier-based limiter entirely)."""

from ..config import settings
from ..utils import cache

RATE_LIMIT_KEY_PREFIX = "telegram_rate_limit"


async def is_rate_limited(chat_id: int) -> bool:
    assert cache.client is not None, "Redis cache client not initialized."
    key = f"{RATE_LIMIT_KEY_PREFIX}:{chat_id}"
    count = await cache.client.incr(key)
    if count == 1:
        await cache.client.expire(key, settings.TELEGRAM_RATE_LIMIT_WINDOW_SECONDS)
    return count > settings.TELEGRAM_RATE_LIMIT_MAX_MESSAGES
