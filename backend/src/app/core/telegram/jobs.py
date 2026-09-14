"""ARQ job functions for the Telegram channel — registered on `core/worker.py`'s
`WorkerSettings`. Every job opens its own DB session via `local_session()`, same
convention as `core/integrations/jobs.py`."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

import httpx
from arq import Retry

from ...crud.crud_conversation_messages import crud_conversation_messages
from ...crud.crud_telegram_link import crud_telegram_link
from ...schemas.conversation_message import ConversationMessageCreate
from ..db.database import local_session
from ..integrations.jobs import _retry_delay_seconds
from ..llm.conversation import generate_conversation_reply
from ..llm.extraction import run_memory_extraction_pipeline
from ..logger import logging
from ..utils import cache
from .client import telegram_send_message

logger = logging.getLogger(__name__)

PROCESSING_LOCK_PREFIX = "telegram_processing_lock"
PROCESSING_LOCK_TTL_SECONDS = 30


async def process_telegram_message(ctx: dict[str, Any], user_id: str, chat_id: int, text: str) -> None:
    """Per-chat lock, not just per-job: two messages fired in quick succession from the
    same chat would otherwise be picked up by two workers, both reading the same 'recent
    history' before either stores its reply — grounding both LLM calls in identical stale
    context and risking replies landing out of order. The lock serializes processing per
    `chat_id`; a blocked attempt defers and retries rather than proceeding.

    `max_tries=5` in core/worker.py exists ONLY to let that lock-contention retry actually
    happen — it does not reopen the door to retrying a genuinely failed turn. The `Retry`
    below is the sole path that raises before any write happens, so it's always safe to
    retry. Anything that fails *after* the lock is held (the DB writes/LLM calls in the
    `try` block further down) still just propagates uncaught, which ARQ does NOT retry
    regardless of `max_tries` — a retry there would re-store a duplicate
    `ConversationMessage` row, re-run extraction (double Task-candidate creation), and
    could send a duplicate reply. A failed turn's natural recovery is the user sending
    another message, not a silent background retry."""
    assert cache.client is not None, "Redis cache client not initialized."
    lock_key = f"{PROCESSING_LOCK_PREFIX}:{chat_id}"
    acquired = await cache.client.set(lock_key, "1", nx=True, ex=PROCESSING_LOCK_TTL_SECONDS)
    if not acquired:
        raise Retry(defer=2)

    try:
        user_uuid = uuid_pkg.UUID(user_id)
        async with local_session() as db:
            await crud_conversation_messages.create(
                db=db,
                object=ConversationMessageCreate(user_id=user_uuid, role="user", channel="telegram", content=text),
            )  # stored FIRST — even if everything below fails, the raw text isn't lost (the
            #    whole reason this table exists — Telegram has no getChatHistory equivalent)

            try:
                await run_memory_extraction_pipeline(
                    db=db,
                    user_id=user_uuid,
                    source_type="conversation",
                    source_channel="telegram",
                    content=text,
                    embed=True,
                )
            except Exception:
                logger.exception(f"Telegram message extraction failed for user {user_id}; continuing.")
                # A broken extraction call must never prevent the user from getting an actual reply.

            reply_text = await generate_conversation_reply(db, user_uuid)
            await crud_conversation_messages.create(
                db=db,
                object=ConversationMessageCreate(
                    user_id=user_uuid, role="assistant", channel="telegram", content=reply_text
                ),
            )  # NOT extracted — matches the precedent of not running extraction on content
            #    that structurally can't contain the user's own commitments.

            await ctx["redis"].enqueue_job("send_telegram_message", chat_id, reply_text)
    finally:
        await cache.client.delete(lock_key)


async def send_telegram_message(
    ctx: dict[str, Any], chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
) -> None:
    """Updates `telegram_link`'s channel-health columns on failure/success. If `link` is
    `None` at send time (unlinked mid-flight — rare race), the send still attempts
    best-effort; health-column updates are simply skipped."""
    async with local_session() as db:
        link = await crud_telegram_link.get(db=db, telegram_chat_id=chat_id)
        try:
            await telegram_send_message(chat_id, text, reply_markup)
        except httpx.HTTPError as exc:
            # httpx.HTTPError is the common base of both httpx.HTTPStatusError (a real
            # response with a bad status) and httpx.TransportError (timeout, connection
            # refused, DNS failure — no response at all). Only catching HTTPStatusError
            # left transport failures uncaught, and per this module's own retry
            # convention an uncaught exception is NOT retried by ARQ regardless of
            # max_tries — a transient network blip would silently and permanently drop
            # the reply with no health-column signal either.
            logger.exception(f"send_telegram_message failed for chat {chat_id}")
            if link:
                await crud_telegram_link.update(
                    db=db,
                    object={
                        "consecutive_failure_count": link["consecutive_failure_count"] + 1,
                        "last_failure_at": datetime.now(UTC),
                    },
                    id=link["id"],
                )
            raise Retry(defer=_retry_delay_seconds(ctx.get("job_try", 1))) from exc
        else:
            if link and link["consecutive_failure_count"] != 0:
                await crud_telegram_link.update(
                    db=db, object={"consecutive_failure_count": 0, "last_failure_at": None}, id=link["id"]
                )
