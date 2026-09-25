"""ARQ job functions — registered on `core/worker.py`'s `WorkerSettings`. Every job opens
its own DB session via `local_session()` (there's no FastAPI request to inject one from —
the worker is a separate process)."""

import json
import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import Retry
from sqlalchemy import or_, select

from ...crud.crud_integration_connections import crud_integration_connections
from ...crud.crud_memory_extraction_records import crud_memory_extraction_records
from ...crud.crud_users import crud_users
from ...models.integration_connection import IntegrationConnection
from ..config import settings
from ..crypto import encrypt_token
from ..db.database import local_session
from ..goals.onboarding import drop_existing_goal_suggestions
from ..llm.extraction import run_memory_extraction_pipeline
from ..llm.onboarding_synthesis import call_goal_synthesis_llm
from ..logger import logging
from .dedup import is_item_unchanged, mark_item_synced
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

# ARQ job-level retry backoff — minutes-scale, distinct from http_retry.py's sub-second
# HTTP-layer backoff. Applied to process_gmail_notification/process_calendar_webhook/
# run_onboarding_ingestion, the three "process one triggered event" jobs — NOT to the two
# cron jobs below, which already self-heal for free on their next tick (see
# core/worker.py for the registered max_tries ceilings).
RETRY_BASE_DELAY_SECONDS = 60
RETRY_MAX_DELAY_SECONDS = 900
ONBOARDING_MAX_TRIES = 3
ONBOARDING_JOB_TIMEOUT_SECONDS = 1800


def _retry_delay_seconds(job_try: int) -> int:
    delay = RETRY_BASE_DELAY_SECONDS * pow(2, job_try - 1)
    return min(int(delay), RETRY_MAX_DELAY_SECONDS)


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
    `emailAddress` to a connection, enqueues `process_gmail_notification` per match.

    Acks each message individually, right after its own handling decision is finalized —
    not batched at the end. A mid-batch failure used to leave already-enqueued messages
    unacked too, so Pub/Sub's redelivery would enqueue them a second time; per-message
    acking narrows that window to just the one message that failed. The deterministic
    `_job_id` passed to `enqueue_job` below is defense-in-depth on top of that: even a
    redelivered duplicate in the remaining narrow window is a safe no-op at the ARQ layer,
    since a job with that ID is already in-flight or its result is still cached."""
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
                await ack_messages([message["ack_id"]])
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
                await ack_messages([message["ack_id"]])
                continue

            job_id = f"gmail-notif-{connection['id']}-{new_history_id}"
            try:
                await ctx["redis"].enqueue_job(
                    "process_gmail_notification", str(connection["id"]), new_history_id, _job_id=job_id
                )
            except Exception:
                logger.exception(
                    f"Failed to enqueue process_gmail_notification for connection {connection['id']}, "
                    "leaving unacked for Pub/Sub redelivery."
                )
                continue

            await ack_messages([message["ack_id"]])


async def process_gmail_notification(ctx: dict[str, Any], connection_id: str, new_history_id: str) -> None:
    """A transient failure anywhere below raises `arq.Retry` with exponential backoff
    (`_retry_delay_seconds`), bounded by the `max_tries` registered on this function in
    `core/worker.py`. Because `history_id` only advances after the whole loop succeeds, a
    retried run re-checks the same delta — but items already synced before the failure
    are now cheap `is_item_unchanged` no-ops instead of a repeat LLM call."""
    async with local_session() as db:
        connection = await crud_integration_connections.get(db=db, id=uuid_pkg.UUID(connection_id))
        if not connection or connection["revoked_at"] is not None:
            return

        try:
            access_token = await get_valid_access_token(db, connection)

            try:
                history_entries = await gmail_list_history(access_token, connection["history_id"] or new_history_id)
                message_ids = _message_ids_from_history(history_entries)
            except GmailHistoryExpiredError:
                candidate_messages = await gmail_list_messages(access_token, EMAIL_INGESTION_QUERY)
                message_ids = [m["id"] for m in candidate_messages]

            for message_id in message_ids:
                message = await gmail_get_message(access_token, message_id)
                # A history delta doesn't respect the q= filter used by gmail_list_messages
                # — re-check each candidate actually carries a STARRED/IMPORTANT label.
                if not message_matches_ingestion_labels(message):
                    continue

                content = parse_gmail_message(message)
                unchanged, existing_row = await is_item_unchanged(
                    db, connection["user_id"], "email", message_id, content
                )
                if unchanged:
                    continue

                record = await run_memory_extraction_pipeline(
                    db=db,
                    user_id=connection["user_id"],
                    source_type="email",
                    source_channel=None,
                    content=content,
                    embed=True,
                )
                await mark_item_synced(
                    db, connection["user_id"], "email", message_id, content, record["id"], existing_row
                )

            # A plain dict, not a schema instance — see token_refresh.py's comment on why
            # every internal-only FastCRUD update in this codebase goes through a dict.
            await crud_integration_connections.update(
                db=db,
                object={"history_id": new_history_id},
                id=connection["id"],
            )
        except Exception as exc:
            logger.exception(f"process_gmail_notification failed for connection {connection_id}")
            raise Retry(defer=_retry_delay_seconds(ctx.get("job_try", 1))) from exc


async def process_calendar_webhook(ctx: dict[str, Any], connection_id: str) -> None:
    """Every ping re-lists the whole `CALENDAR_INGESTION_WINDOW`, not just a delta (see
    decisions-log.md N-17) — `is_item_unchanged`/`mark_item_synced` below is what makes
    that cheap: an unchanged event is skipped before the LLM call instead of producing a
    duplicate `memory_extraction_record`. A transient failure raises `arq.Retry` with
    exponential backoff, bounded by the `max_tries`/`timeout` registered on this function
    in `core/worker.py`."""
    async with local_session() as db:
        connection = await crud_integration_connections.get(db=db, id=uuid_pkg.UUID(connection_id))
        if not connection or connection["revoked_at"] is not None:
            return

        try:
            access_token = await get_valid_access_token(db, connection)

            now = datetime.now(UTC)
            events = await calendar_list_events(access_token, now, now + CALENDAR_INGESTION_WINDOW)

            for event in events:
                event_id = event.get("id")
                content = parse_calendar_event(event)

                existing_row = None
                if event_id is None:
                    # Calendar events should always carry an "id" per Google's API — a
                    # missing one is itself an anomaly worth logging, not something to
                    # paper over with a shared fallback key (two id-less events would
                    # collide and overwrite each other's ingestion_sync row). Always
                    # process it; just skip dedup entirely for this one item.
                    logger.warning(
                        f"Calendar event with no id for connection {connection_id}; processing without dedup."
                    )
                else:
                    unchanged, existing_row = await is_item_unchanged(
                        db, connection["user_id"], "calendar", event_id, content
                    )
                    if unchanged:
                        continue

                record = await run_memory_extraction_pipeline(
                    db=db,
                    user_id=connection["user_id"],
                    source_type="calendar",
                    source_channel=None,
                    content=content,
                    embed=False,
                )
                if event_id is not None:
                    await mark_item_synced(
                        db, connection["user_id"], "calendar", event_id, content, record["id"], existing_row
                    )
        except Exception as exc:
            logger.exception(f"process_calendar_webhook failed for connection {connection_id}")
            raise Retry(defer=_retry_delay_seconds(ctx.get("job_try", 1))) from exc


async def _recover_synced_summary(db: Any, source_label: str, existing_row: dict[str, Any]) -> tuple[str, str] | None:
    """Onboarding-only dedup-skip recovery. `run_onboarding_ingestion` rebuilds its
    `summaries` list fresh on every attempt — on a retry, an item already synced by a
    prior attempt now dedup-skips via `is_item_unchanged`, and without this it would
    silently vanish from `summaries` (and therefore from the goal-synthesis call) even
    though it was successfully extracted. Recovers it by following the `ingestion_sync`
    row's `memory_record_id` back to the `MemoryExtractionRecord` an earlier attempt (or
    the steady-state webhook/notification jobs) already created, and re-using its stored
    `summary`. Returns None (nothing to append) only in the unreachable-in-practice case
    where that record has since been deleted out from under a live memory_record_id."""
    memory_record_id = existing_row["memory_record_id"]
    record = await crud_memory_extraction_records.get(db=db, id=memory_record_id)
    if not record:
        logger.warning(f"ingestion_sync row references missing memory_extraction_record {memory_record_id}")
        return None
    return source_label, record["summary"]


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
    not allowed to abort the whole batch. `is_item_unchanged`/`mark_item_synced` skip
    items already extracted by a prior onboarding run OR by the steady-state webhook/
    notification jobs — the shared `ingestion_sync` table doesn't care which path synced
    an item first.

    A transient outer failure raises `arq.Retry` (exponential backoff) up to
    `ONBOARDING_MAX_TRIES` attempts — the "missing connection" case above is a permanent
    condition retrying can't fix, so it resets `onboarding_status` to `not_started`
    immediately, unconditionally. Only once transient retries are exhausted does the
    **outer** except do the same reset, giving the user a real recovery path via the
    resume endpoint rather than leaving them stuck on `pending` forever."""
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
                    unchanged, existing_row = await is_item_unchanged(db, user_uuid, "email", message_id, content)
                    if unchanged:
                        if existing_row:
                            recovered = await _recover_synced_summary(db, "email", existing_row)
                            if recovered:
                                summaries.append(recovered)
                        continue
                    record = await run_memory_extraction_pipeline(
                        db=db, user_id=user_uuid, source_type="email", source_channel=None, content=content, embed=True
                    )
                    summaries.append(("email", record["summary"]))
                    await mark_item_synced(db, user_uuid, "email", message_id, content, record["id"], existing_row)
                except Exception:
                    logger.exception(f"Onboarding ingestion: failed on Gmail message {message_id} for user {user_id}")
                    continue

            calendar_access_token = await get_valid_access_token(db, calendar_connection)
            now = datetime.now(UTC)
            for event in await calendar_list_events(calendar_access_token, now, now + CALENDAR_INGESTION_WINDOW):
                event_id = event.get("id")
                try:
                    content = parse_calendar_event(event)

                    existing_row = None
                    if event_id is None:
                        # See process_calendar_webhook's identical reasoning — no shared
                        # fallback key, always process, just skip dedup for this item.
                        logger.warning(
                            f"Onboarding ingestion: calendar event with no id for user {user_id}; "
                            "processing without dedup."
                        )
                    else:
                        unchanged, existing_row = await is_item_unchanged(db, user_uuid, "calendar", event_id, content)
                        if unchanged:
                            if existing_row:
                                recovered = await _recover_synced_summary(db, "calendar", existing_row)
                                if recovered:
                                    summaries.append(recovered)
                            continue

                    record = await run_memory_extraction_pipeline(
                        db=db,
                        user_id=user_uuid,
                        source_type="calendar",
                        source_channel=None,
                        content=content,
                        embed=False,
                    )
                    summaries.append(("calendar", record["summary"]))
                    if event_id is not None:
                        await mark_item_synced(db, user_uuid, "calendar", event_id, content, record["id"], existing_row)
                except Exception:
                    logger.exception(f"Onboarding ingestion: failed on calendar event {event_id} for user {user_id}")
                    continue

            suggested_goals: list[dict[str, Any]] = []
            if summaries:
                result = await call_goal_synthesis_llm(summaries)
                # Confident email goals were already auto-created above (through the
                # extraction pipeline) — never suggest a goal the user already has.
                kept = await drop_existing_goal_suggestions(db, user_uuid, result.suggested_goals)
                suggested_goals = [g.model_dump(mode="json") for g in kept]

            await crud_users.update(
                db=db,
                object={"onboarding_status": "ready", "onboarding_suggested_goals": suggested_goals},
                id=user_uuid,
            )
        except Exception as exc:
            job_try = ctx.get("job_try", 1)
            if job_try < ONBOARDING_MAX_TRIES:
                logger.exception(f"Onboarding ingestion failed for user {user_id} (attempt {job_try}); retrying.")
                raise Retry(defer=_retry_delay_seconds(job_try)) from exc

            logger.exception(
                f"Onboarding ingestion failed outright for user {user_id} after {job_try} attempts; "
                "resetting to not_started."
            )
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
