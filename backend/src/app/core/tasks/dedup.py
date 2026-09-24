"""Near-duplicate skip for tasks auto-created by `run_memory_extraction_pipeline`
(email / conversation / calendar — decisions-log.md 2026-09-24). Notion is not covered:
it already blocks re-creation through its kept `notion_block_link` rows, with no time limit.

Task titles are embedded on the fly with the local model, never stored — that keeps the
2026-09-06 embeddings-scope decision (only summaries get stored embeddings) intact. Cost
stays low because this only runs when an extraction yields at least one confident
candidate, embeds everything in one batch call, and compares against a bounded list.
"""

import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_tasks import crud_tasks
from ...models.task import Task
from ...schemas.memory_extraction_record import ExtractedTaskCandidate
from ..config import settings
from ..llm.embedding_model import embed_texts
from ..llm.similarity import cosine_similarity
from ..logger import logging
from .sticky import STICKY_FLAG_BY_FIELD

logger = logging.getLogger(__name__)

# Never `title` (a match already means "the same task") and never `urgency` (always has a
# value — "medium" by default on both tasks and extracted candidates, so it's never blank).
BLANK_FILLABLE_FIELDS = ("due_date", "description", "effort_level")


async def load_dedup_pool(db: AsyncSession, user_id: uuid_pkg.UUID) -> list[dict[str, Any]]:
    """The user's open tasks, plus done/deleted ones from the last
    `TASK_DEDUP_LOOKBACK_DAYS`. Plain SQLAlchemy, not FastCRUD — the OR spans several
    columns, which FastCRUD's per-column `__or` can't express. The one task read that
    includes deleted rows on purpose. "Done within N days" uses `updated_at` as a stand-in:
    there is no `completed_at` column, and a task only becomes done through an update."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.TASK_DEDUP_LOOKBACK_DAYS)
    stmt = (
        select(
            Task.id,
            Task.title,
            Task.description,
            Task.due_date,
            Task.effort_level,
            Task.status,
            Task.is_deleted,
            Task.description_manually_set,
            Task.effort_level_manually_set,
        )
        .where(
            Task.user_id == user_id,
            or_(
                and_(Task.is_deleted.is_(False), Task.status == "open"),
                and_(Task.is_deleted.is_(False), Task.status == "done", Task.updated_at >= cutoff),
                and_(Task.is_deleted.is_(True), Task.deleted_at >= cutoff),
            ),
        )
        .order_by(Task.created_at.desc())
        .limit(settings.TASK_DEDUP_MAX_EXISTING_TASKS)
    )
    result = await db.execute(stmt)
    pool = [dict(row) for row in result.mappings().all()]
    if len(pool) >= settings.TASK_DEDUP_MAX_EXISTING_TASKS:
        logger.warning(
            f"Task dedup pool for user {user_id} hit the {settings.TASK_DEDUP_MAX_EXISTING_TASKS}-task cap; "
            "older tasks were not compared."
        )
    return pool


def _blank_fields(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Fields empty on `target` (and not sticky there) that `source` has a value for."""
    blanks = {}
    for field in BLANK_FILLABLE_FIELDS:
        flag = STICKY_FLAG_BY_FIELD.get(field)
        if flag and target.get(flag):
            continue
        if not target.get(field) and source.get(field):
            blanks[field] = source[field]
    return blanks


def merge_candidate_duplicates(
    candidates: list[ExtractedTaskCandidate], embeddings: list[list[float]]
) -> list[tuple[ExtractedTaskCandidate, list[float]]]:
    """In-memory dedup within one extraction result, before anything is written. Highest
    confidence wins; a dropped duplicate's details fill the kept candidate's blanks."""
    ordered = sorted(zip(candidates, embeddings, strict=True), key=lambda pair: pair[0].confidence, reverse=True)
    kept: list[tuple[ExtractedTaskCandidate, list[float]]] = []
    for candidate, embedding in ordered:
        match_index = next(
            (
                index
                for index, (_, kept_embedding) in enumerate(kept)
                if cosine_similarity(embedding, kept_embedding) >= settings.TASK_DEDUP_SIMILARITY_THRESHOLD
            ),
            None,
        )
        if match_index is None:
            kept.append((candidate, embedding))
            continue

        kept_candidate, kept_embedding = kept[match_index]
        blanks = _blank_fields(kept_candidate.model_dump(), candidate.model_dump())
        if blanks:
            kept[match_index] = (kept_candidate.model_copy(update=blanks), kept_embedding)
    return kept


def find_best_match(
    embedding: list[float], pool: list[dict[str, Any]], pool_embeddings: list[list[float]]
) -> tuple[dict[str, Any], float] | None:
    """The pool task with the highest similarity, if it clears the threshold."""
    best: tuple[dict[str, Any], float] | None = None
    for task, task_embedding in zip(pool, pool_embeddings, strict=True):
        score = cosine_similarity(embedding, task_embedding)
        if score >= settings.TASK_DEDUP_SIMILARITY_THRESHOLD and (best is None or score > best[1]):
            best = (task, score)
    return best


async def fill_blanks(db: AsyncSession, existing: dict[str, Any], candidate: ExtractedTaskCandidate) -> None:
    """Copies only empty, non-sticky `BLANK_FILLABLE_FIELDS` from `candidate` onto the
    existing open task — never overwrites a filled field. Runs inside the extraction
    pipeline's transaction (`commit=False`). Updates `existing` in place so a second
    candidate matching the same task in this run sees the fresh values."""
    fields = _blank_fields(existing, candidate.model_dump())
    if not fields:
        return
    await crud_tasks.update(db=db, object=fields, id=existing["id"], commit=False)
    existing.update(fields)


async def resolve_candidates(
    db: AsyncSession, user_id: uuid_pkg.UUID, candidates: list[ExtractedTaskCandidate]
) -> list[ExtractedTaskCandidate]:
    """Returns only the candidates that should become NEW tasks. A near-duplicate of an
    open task fills that task's blanks instead; a near-duplicate of a recently done or
    deleted task is skipped."""
    if not candidates:
        return []

    pool = await load_dedup_pool(db, user_id)
    embeddings = await embed_texts([candidate.title for candidate in candidates] + [task["title"] for task in pool])
    candidate_embeddings, pool_embeddings = embeddings[: len(candidates)], embeddings[len(candidates) :]

    to_create = []
    for candidate, embedding in merge_candidate_duplicates(candidates, candidate_embeddings):
        match = find_best_match(embedding, pool, pool_embeddings)
        if match is None:
            to_create.append(candidate)
            continue

        existing, score = match
        if existing["status"] == "open" and not existing["is_deleted"]:
            await fill_blanks(db, existing, candidate)
        logger.info(f"Skipped near-duplicate task candidate (similarity {score:.3f}) of task {existing['id']}")
    return to_create
