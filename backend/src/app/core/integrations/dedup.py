"""Per-item ingestion dedup — a read-before-extract / write-after-extract pair used by
every jobs.py ingestion call site (Gmail notification processing, Calendar webhook
processing, onboarding bulk ingestion). Deliberately not folded into
`run_memory_extraction_pipeline` itself, since that pipeline is also called by the
source-agnostic `POST /memory/ingest` route (`api/v1/memory.py`), which has no stable
external id to key on.

Plain sha256 fingerprint, not SimHash — Gmail/Calendar content is one deterministic
parsed string per fetch (see `gmail.py::parse_gmail_message`,
`google_calendar.py::parse_calendar_event`), not free-text block editing, so there's no
"typo vs. real edit" fuzzy-similarity distinction to make the way there is for Notion's
(not-yet-built) block sync. See decisions-log.md.
"""

import hashlib
import uuid as uuid_pkg
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_ingestion_sync import crud_ingestion_sync
from ...schemas.ingestion_sync import IngestionSourceType, IngestionSyncCreateInternal
from ..logger import logging

logger = logging.getLogger(__name__)


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def is_item_unchanged(
    db: AsyncSession,
    user_id: uuid_pkg.UUID,
    source_type: IngestionSourceType,
    external_id: str,
    content: str,
) -> tuple[bool, dict[str, Any] | None]:
    """Read-only. Returns `(unchanged, existing_row)`. `unchanged` is True only when a
    prior synced row exists for this exact (user_id, source_type, external_id) and its
    stored fingerprint matches `content`'s current hash — i.e. "safe to skip the LLM
    pipeline entirely." A never-seen external_id, or a seen one whose content has since
    changed, both return `unchanged=False`.

    `existing_row` is exactly what `crud_ingestion_sync.get()` returned here (or `None` if
    never synced) — every call site passes it straight into `mark_item_synced` so that
    function doesn't re-fetch the same row a second time. `run_onboarding_ingestion`'s
    dedup-skip path also reads `existing_row["memory_record_id"]` off it to recover a
    previously-synced item's summary for this attempt's synthesis call (see jobs.py's
    `_recover_synced_summary`)."""
    existing = await crud_ingestion_sync.get(db=db, user_id=user_id, source_type=source_type, external_id=external_id)
    if not existing:
        return False, None
    unchanged = bool(existing["content_fingerprint"] == _fingerprint(content))
    return unchanged, existing


async def mark_item_synced(
    db: AsyncSession,
    user_id: uuid_pkg.UUID,
    source_type: IngestionSourceType,
    external_id: str,
    content: str,
    memory_record_id: uuid_pkg.UUID | None,
    existing_row: dict[str, Any] | None,
) -> None:
    """Call only AFTER `run_memory_extraction_pipeline` succeeds — a failed extraction
    must never mark an item "seen", so it's naturally retried on the next ingestion pass.
    Upserts: creates the row on first sync, updates fingerprint + memory_record_id on a
    later, changed sync.

    `existing_row` must be the value `is_item_unchanged` returned for this same
    (user_id, source_type, external_id) earlier in the same call site's iteration — passing
    it in (rather than re-fetching here) saves a redundant round-trip for every changed
    item. Safe even though it was fetched slightly earlier: only `existing_row["id"]` is
    used, which is immutable across updates, so a row that changed underneath in the
    interim still updates correctly.

    Two ingestion code paths (e.g. onboarding's bulk pass and a live webhook/notification
    job) can race to first-sync the same never-before-seen item — both see "not yet
    synced" (`existing_row=None`), both already ran their own extraction call (a
    pre-existing, accepted duplicate-extraction risk, not introduced here), and then both
    try to insert this row. The unique constraint on (user_id, source_type, external_id)
    makes the loser raise IntegrityError; caught and rolled back here rather than crashing
    that job run and poisoning the session for the rest of its batch loop."""
    fingerprint = _fingerprint(content)

    if existing_row:
        await crud_ingestion_sync.update(
            db=db,
            object={"content_fingerprint": fingerprint, "memory_record_id": memory_record_id},
            id=existing_row["id"],
        )
        return

    try:
        await crud_ingestion_sync.create(
            db=db,
            object=IngestionSyncCreateInternal(
                user_id=user_id,
                source_type=source_type,
                external_id=external_id,
                content_fingerprint=fingerprint,
                memory_record_id=memory_record_id,
            ),
        )
    except IntegrityError:
        await db.rollback()
        logger.info(f"ingestion_sync race for {source_type}:{external_id} (user {user_id}) — already synced.")
