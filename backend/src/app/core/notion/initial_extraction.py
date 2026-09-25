"""Initial-extraction orchestrator (`page.created` path) — chunks a new page's blocks,
runs one extraction call per chunk in parallel, deduplicates candidate items across
overlapping chunks via embedding similarity (MyPA's existing infra — explicitly not an
LLM pairwise-comparison call, since that's only needed by systems with no embeddings
available at all), and fails loud rather than silently truncating a page too large to
safely cover. See decisions-log.md's 2026-09-23 entry for the full design rationale.
"""

import asyncio
import uuid as uuid_pkg
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_memory_extraction_records import crud_memory_extraction_records
from ...crud.crud_notion_block_sync import crud_notion_block_sync
from ...schemas.memory_extraction_record import MemoryExtractionRecordCreate
from ...schemas.notion_block_sync import NotionBlockSyncCreateInternal
from ...schemas.notion_classification import NotionChunkExtractedItem
from ..config import settings
from ..goals.context import load_open_goals, resolve_goal_link
from ..llm.embedding_model import embed_text
from ..llm.notion_initial_extraction import extract_chunk
from ..llm.similarity import cosine_similarity
from ..logger import logging
from .chunking import chunk_blocks
from .client import NotionBlock, extract_plain_text, fetch_all_blocks_recursive
from .persistence import NotionPersistenceAction, persist_notion_block_outcome
from .simhash import compute_simhash

logger = logging.getLogger(__name__)


async def _flag_oversized_page(db: AsyncSession, user_id: uuid_pkg.UUID, page_id: str, chunk_count: int) -> None:
    logger.error(f"Notion page {page_id} exceeds the {settings.NOTION_MAX_CHUNKS_PER_PAGE}-chunk ceiling — flagged.")
    await crud_memory_extraction_records.create(
        db=db,
        object=MemoryExtractionRecordCreate(
            user_id=user_id,
            source_type="notion",
            source_channel=None,
            summary=(
                f"Notion page {page_id} has {chunk_count} chunks, exceeding the "
                f"{settings.NOTION_MAX_CHUNKS_PER_PAGE}-chunk ceiling — flagged for manual review, "
                "not processed."
            ),
            tasks=[],
        ),
    )


async def _dedup_items(
    items: list[NotionChunkExtractedItem],
) -> list[NotionChunkExtractedItem]:
    """Sorts by confidence descending, greedily accepts each candidate whose embedding
    isn't near-duplicate (>= threshold cosine similarity) of any already-accepted item —
    the higher-confidence version of a fact appearing in two overlapping chunks wins."""
    ordered = sorted(items, key=lambda item: item.confidence, reverse=True)
    accepted: list[NotionChunkExtractedItem] = []
    accepted_embeddings: list[list[float]] = []

    for item in ordered:
        embedding = await embed_text(f"{item.title}. {item.description or ''}")
        is_duplicate = any(
            cosine_similarity(embedding, other) >= settings.NOTION_DEDUP_SIMILARITY_THRESHOLD
            for other in accepted_embeddings
        )
        if not is_duplicate:
            accepted.append(item)
            accepted_embeddings.append(embedding)
    return accepted


async def run_initial_extraction(db: AsyncSession, user_id: uuid_pkg.UUID, access_token: str, page_id: str) -> None:
    blocks = await fetch_all_blocks_recursive(access_token, page_id)
    if not blocks:
        return

    chunks = chunk_blocks(blocks)
    if len(chunks) > settings.NOTION_MAX_CHUNKS_PER_PAGE:
        await _flag_oversized_page(db, user_id, page_id, len(chunks))
        return

    full_page_text = "\n".join(block.plain_text for block in blocks if block.plain_text)
    # Loaded once per page, so a confident task can be linked to one of them. A goal created
    # from this same page can't be linked (it doesn't exist yet) — open item N-29.
    open_goals = await load_open_goals(db, user_id)

    results = await asyncio.gather(
        *(extract_chunk(full_page_text, chunk, open_goals) for chunk in chunks), return_exceptions=True
    )

    all_items: list[NotionChunkExtractedItem] = []
    for chunk, result in zip(chunks, results, strict=True):
        if isinstance(result, BaseException):
            chunk_block_ids = [block.id for block in chunk]
            logger.error(
                f"Notion chunk extraction failed for page {page_id}, blocks {chunk_block_ids}", exc_info=result
            )
            continue
        all_items.extend(result.items)

    accepted_items = await _dedup_items(all_items)

    items_by_block: dict[str, list[NotionChunkExtractedItem]] = defaultdict(list)
    for item in accepted_items:
        items_by_block[item.source_block_id].append(item)

    blocks_by_id: dict[str, NotionBlock] = {block.id: block for block in blocks}

    for block_id, items in items_by_block.items():
        block = blocks_by_id.get(block_id)
        if block is None:
            continue
        try:
            actions = [
                NotionPersistenceAction(
                    kind="create",
                    item_type=item.item_type,
                    title=item.title,
                    description=item.description,
                    due_date=item.due_date,
                    urgency=item.urgency,
                    effort_level=item.effort_level,
                    horizon=item.horizon,
                    confidence=item.confidence,
                    goal_id=(
                        resolve_goal_link(item.goal_ref, item.goal_link_confidence, open_goals)
                        if item.item_type == "task"
                        else None
                    ),
                )
                for item in items
            ]
            block_summary = extract_plain_text(block.raw)
            await persist_notion_block_outcome(db, user_id, block_id, page_id, block_summary, actions)
            await _write_watermark(db, user_id, page_id, block)
        except Exception:
            logger.exception(f"Failed to persist Notion initial-extraction outcome for block {block_id}")
            continue

    # Blocks that produced no accepted items still get a watermark, so the edit-path's
    # stage-1 gate sees them as "already known" going forward rather than treating their
    # NEXT real edit as a brand-new, never-seen block.
    for block in blocks:
        if block.id not in items_by_block:
            try:
                await _write_watermark(db, user_id, page_id, block)
            except Exception:
                logger.exception(f"Failed to write initial watermark for block {block.id}")
                continue


async def _write_watermark(db: AsyncSession, user_id: uuid_pkg.UUID, page_id: str, block: NotionBlock) -> None:
    """`page_id` is always the top-level shared page — passed down explicitly rather
    than derived from `block.parent`, since a nested block's own `parent` is its
    immediate containing block, not the page (see `notion_block_sync`'s `(user_id,
    notion_page_id)` index, which reconciliation needs to pull every tracked block for
    ONE PAGE, not one immediate-parent block)."""
    existing = await crud_notion_block_sync.get(db=db, user_id=user_id, notion_block_id=block.id)
    fingerprint = compute_simhash(block.plain_text)
    if existing:
        await crud_notion_block_sync.update(
            db=db,
            object={"last_edited_time": block.last_edited_time, "content_fingerprint": fingerprint},
            id=existing["id"],
        )
    else:
        await crud_notion_block_sync.create(
            db=db,
            object=NotionBlockSyncCreateInternal(
                user_id=user_id,
                notion_block_id=block.id,
                notion_page_id=page_id,
                last_edited_time=block.last_edited_time,
                content_fingerprint=fingerprint,
            ),
        )
