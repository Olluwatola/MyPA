"""ARQ job functions — registered on `core/worker.py`'s `WorkerSettings`. Every job opens
its own DB session via `local_session()` (there's no FastAPI request to inject one from —
the worker is a separate process)."""

import json
import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from ...crud.crud_integration_connections import crud_integration_connections
from ...crud.crud_users import crud_users
from ...models.integration_connection import IntegrationConnection
from ..config import settings
from ..crypto import encrypt_token
from ..db.database import local_session
from ..llm.extraction import run_memory_extraction_pipeline
from ..llm.onboarding_synthesis import call_goal_synthesis_llm
from ..logger import logging
from .gmail import (
    EMAIL_INGESTION_QUERY,
    GmailHistoryExpiredError,
    gmail_get_message,
    gmail_list_history,
    gmail_list_messages,
    gmail_watch,
    message_matches_ingestion_labels,
    parse_gmail_message,
)
from .google_calendar import calendar_list_events, calendar_watch, parse_calendar_event
from .pubsub import ack_messages, pull_messages
from .token_refresh import get_valid_access_token

logger = logging.getLogger(__name__)

CALENDAR_INGESTION_WINDOW = timedelta(days=14)
WATCH_RENEWAL_THRESHOLD = timedelta(hours=6)

# Mirrors every column on IntegrationConnection — used to turn an ORM row from the raw
# `select()` below (renew_watches_before_expiry needs an OR condition FastCRUD's filter
# kwargs can't express) into the same plain-dict shape every other CRUD call in this
# module already works with.
_CONNECTION_FIELDS = (
    "id",
    "user_id",
    "type",
    "provider",
    "access_token",
    "connected_at",
    "external_account_identifier",
    "refresh_token",
    "token_expires_at",
    "scopes",
    "revoked_at",
    "watch_channel_id",
    "watch_resource_id",
    "watch_expires_at",
    "history_id",
    "channel_token",
)


async def pull_gmail_pubsub_notifications(ctx: dict[str, Any]) -> None:
    """Cron, every 15s. Pulls up to 20 Pub/Sub messages, matches each notification's
    `emailAddress` to a connection, enqueues `process_gmail_notification` per match, acks
    all pulled messages (safe since downstream processing is idempotent on `history_id`)
    — skips+acks (logs, doesn't crash the batch) any unmatched address."""
    messages = await pull_messages(max_messages=20)
    if not messages:
        return

    async with local_session() as db:
        for message in messages:
            try:
                notification = json.loads(message["data"])
                email_address = notification["emailAddress"]
                new_history_id = str(notification["historyId"])
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning(f"Malformed Gmail Pub/Sub notification, skipping: {exc}")
                continue

            connection = await crud_integration_connections.get(
                db=db,
                external_account_identifier=email_address,
                type="email",
                provider="google",
                revoked_at=None,
            )
            if not connection:
                logger.warning(f"No matching connection for Gmail notification address {email_address}, skipping.")
                continue

            await ctx["redis"].enqueue_job("process_gmail_notification", str(connection["id"]), new_history_id)

    await ack_messages([m["ack_id"] for m in messages])


async def process_gmail_notification(ctx: dict[str, Any], connection_id: str, new_history_id: str) -> None:
    async with local_session() as db:
        connection = await crud_integration_connections.get(db=db, id=uuid_pkg.UUID(connection_id))
        if not connection or connection["revoked_at"] is not None:
            return

        access_token = await get_valid_access_token(db, connection)

        try:
            history_entries = await gmail_list_history(access_token, connection["history_id"] or new_history_id)
            message_ids = _message_ids_from_history(history_entries)
        except GmailHistoryExpiredError:
            candidate_messages = await gmail_list_messages(access_token, EMAIL_INGESTION_QUERY)
            message_ids = [m["id"] for m in candidate_messages]

        for message_id in message_ids:
            message = await gmail_get_message(access_token, message_id)
            # A history delta doesn't respect the q= filter used by gmail_list_messages —
            # re-check each candidate actually carries a STARRED/IMPORTANT label.
            if not message_matches_ingestion_labels(message):
                continue

            content = parse_gmail_message(message)
            await run_memory_extraction_pipeline(
                db=db,
                user_id=connection["user_id"],
                source_type="email",
                source_channel=None,
                content=content,
                embed=True,
            )

        # A plain dict, not a schema instance — see token_refresh.py's comment on why
        # every internal-only FastCRUD update in this codebase goes through a dict.
        await crud_integration_connections.update(
            db=db,
            object={"history_id": new_history_id},
            id=connection["id"],
        )


async def process_calendar_webhook(ctx: dict[str, Any], connection_id: str) -> None:
    async with local_session() as db:
        connection = await crud_integration_connections.get(db=db, id=uuid_pkg.UUID(connection_id))
        if not connection or connection["revoked_at"] is not None:
            return

        access_token = await get_valid_access_token(db, connection)

        now = datetime.now(UTC)
        events = await calendar_list_events(access_token, now, now + CALENDAR_INGESTION_WINDOW)

        for event in events:
            content = parse_calendar_event(event)
            await run_memory_extraction_pipeline(
                db=db,
                user_id=connection["user_id"],
                source_type="calendar",
                source_channel=None,
                content=content,
                embed=False,
            )


async def run_onboarding_ingestion(ctx: dict[str, Any], user_id: str) -> None:
    """Full bulk pass over recent Gmail + Calendar content, triggered on-demand — distinct
    from `process_gmail_notification`/`process_calendar_webhook`, which are delta passes
    triggered by a webhook. Fired both from the OAuth callback (first run) and from
    `POST /onboarding/run` (resume) via `trigger_onboarding_run` — always regenerates and
    overwrites the prior suggestion set, no staleness heuristic.

    Reuses 1.4's exact steady-state ingestion windows (`EMAIL_INGESTION_QUERY`,
    `CALENDAR_INGESTION_WINDOW`) — neither PRD states an onboarding-specific bound.

    Per-item fault isolation (newly needed here — a full 14-day backlog is a real,
    higher-likelihood failure mode than an incremental delta) matches the pattern already
    used by `renew_watches_before_expiry`: one bad message/event is logged and skipped,
    not allowed to abort the whole batch. An **outer** try/except resets
    `onboarding_status` to `not_started` on total failure, giving the user a real recovery
    path via the resume endpoint rather than leaving them stuck on `pending`."""
    user_uuid = uuid_pkg.UUID(user_id)
    async with local_session() as db:
        email_connection = await crud_integration_connections.get(
            db=db, user_id=user_uuid, type="email", provider="google", revoked_at=None
        )
        calendar_connection = await crud_integration_connections.get(
            db=db, user_id=user_uuid, type="calendar", provider="google", revoked_at=None
        )
        if not email_connection or not calendar_connection:
            logger.warning(f"Onboarding ingestion: missing connection for user {user_id}, aborting.")
            await crud_users.update(db=db, object={"onboarding_status": "not_started"}, id=user_uuid)
            return

        try:
            summaries: list[tuple[str, str]] = []

            email_access_token = await get_valid_access_token(db, email_connection)
            for message_stub in await gmail_list_messages(email_access_token, EMAIL_INGESTION_QUERY):
                message_id = message_stub["id"]
                try:
                    message = await gmail_get_message(email_access_token, message_id)
                    content = parse_gmail_message(message)
                    record = await run_memory_extraction_pipeline(
                        db=db, user_id=user_uuid, source_type="email", source_channel=None, content=content, embed=True
                    )
                    summaries.append(("email", record["summary"]))
                except Exception:
                    logger.exception(f"Onboarding ingestion: failed on Gmail message {message_id} for user {user_id}")
                    continue

            calendar_access_token = await get_valid_access_token(db, calendar_connection)
            now = datetime.now(UTC)
            for event in await calendar_list_events(calendar_access_token, now, now + CALENDAR_INGESTION_WINDOW):
                event_id = event.get("id", "?")
                try:
                    content = parse_calendar_event(event)
                    record = await run_memory_extraction_pipeline(
                        db=db,
                        user_id=user_uuid,
                        source_type="calendar",
                        source_channel=None,
                        content=content,
                        embed=False,
                    )
                    summaries.append(("calendar", record["summary"]))
                except Exception:
                    logger.exception(f"Onboarding ingestion: failed on calendar event {event_id} for user {user_id}")
                    continue

            suggested_goals: list[dict[str, Any]] = []
            if summaries:
                result = await call_goal_synthesis_llm(summaries)
                suggested_goals = [g.model_dump(mode="json") for g in result.suggested_goals]

            await crud_users.update(
                db=db,
                object={"onboarding_status": "ready", "onboarding_suggested_goals": suggested_goals},
                id=user_uuid,
            )
        except Exception:
            logger.exception(f"Onboarding ingestion failed outright for user {user_id}; resetting to not_started.")
            await crud_users.update(db=db, object={"onboarding_status": "not_started"}, id=user_uuid)


async def renew_watches_before_expiry(ctx: dict[str, Any]) -> None:
    """Cron, hourly. Matches `revoked_at IS NULL AND (watch_expires_at IS NULL OR
    watch_expires_at < now() + 6h)`. Re-registers per type. No separate "register on
    first connect" job — this same query already matches every brand-new connection
    (`watch_expires_at IS NULL`), so one code path handles both first-registration and
    renewal."""
    threshold = datetime.now(UTC) + WATCH_RENEWAL_THRESHOLD

    async with local_session() as db:
        stmt = select(IntegrationConnection).where(
            IntegrationConnection.revoked_at.is_(None),
            or_(
                IntegrationConnection.watch_expires_at.is_(None),
                IntegrationConnection.watch_expires_at < threshold,
            ),
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        for row in rows:
            connection = {field: getattr(row, field) for field in _CONNECTION_FIELDS}
            try:
                await _renew_one_watch(db, connection)
            except Exception:
                logger.exception(f"Failed to renew watch for integration_connection {connection['id']}")


async def _renew_one_watch(db: Any, connection: dict[str, Any]) -> None:
    access_token = await get_valid_access_token(db, connection)

    if connection["type"] == "email":
        response = await gmail_watch(access_token, settings.GOOGLE_PUBSUB_TOPIC)
        expires_at = datetime.fromtimestamp(int(response["expiration"]) / 1000, tz=UTC)
        await crud_integration_connections.update(
            db=db,
            object={"history_id": str(response["historyId"]), "watch_expires_at": expires_at},
            id=connection["id"],
        )
    else:  # calendar
        channel_id = str(uuid_pkg.uuid4())
        channel_token_plain = str(uuid_pkg.uuid4())
        response = await calendar_watch(
            access_token, channel_id, channel_token_plain, settings.GOOGLE_CALENDAR_WEBHOOK_URL
        )
        expires_at = datetime.fromtimestamp(int(response["expiration"]) / 1000, tz=UTC)
        await crud_integration_connections.update(
            db=db,
            object={
                "watch_channel_id": channel_id,
                "watch_resource_id": response["resourceId"],
                "watch_expires_at": expires_at,
                "channel_token": encrypt_token(channel_token_plain),
            },
            id=connection["id"],
        )


def _message_ids_from_history(history_entries: list[dict[str, Any]]) -> list[str]:
    message_ids: list[str] = []
    for entry in history_entries:
        for added in entry.get("messagesAdded", []):
            message_id = added.get("message", {}).get("id")
            if message_id:
                message_ids.append(message_id)
    return message_ids
