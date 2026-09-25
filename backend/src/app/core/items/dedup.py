"""Near-duplicate skip for tasks and goals auto-created by `run_memory_extraction_pipeline`
(decisions-log.md 2026-09-24), and for onboarding goal suggestions (core/goals/onboarding.py).
Notion is not covered: it already blocks re-creation through its kept `notion_block_link`
rows, with no time limit.

One engine for both types, driven by a small `DedupSpec` (which model, which fields may be
filled, which statuses count as live/closed, which config values). Titles are embedded on
the fly with the local model, never stored — that keeps the 2026-09-06 embeddings-scope
decision (only summaries get stored embeddings) intact. Cost stays low because this only
runs when an extraction yields at least one confident candidate, embeds everything in one
batch call, and compares against a bounded list.
"""

import uuid as uuid_pkg
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_goals import crud_goals
from ...crud.crud_tasks import crud_tasks
from ...models.goal import Goal
from ...models.task import Task
from ...schemas.memory_extraction_record import ExtractedGoal, ExtractedTaskCandidate
from ..config import settings
from ..llm.embedding_model import embed_texts
from ..llm.similarity import cosine_similarity
from ..logger import logging
from .sticky import GOAL_STICKY_FLAGS, TASK_STICKY_FLAGS

logger = logging.getLogger(__name__)

CandidateT = TypeVar("CandidateT", ExtractedTaskCandidate, ExtractedGoal)


@dataclass(frozen=True)
class DedupSpec:
    model: type[Task] | type[Goal]
    crud: Any
    # Fields a near-duplicate may fill on an existing OPEN item — only when empty there
    # and not sticky. Never `title` (a match already means "the same item").
    fillable_fields: tuple[str, ...]
    sticky_flags: dict[str, str]
    # Always in the pool, however old.
    live_statuses: tuple[str, ...]
    # In the pool only if updated within `lookback_days` ("done within N days" uses
    # `updated_at` as a stand-in: there is no `completed_at` column).
    closed_statuses: tuple[str, ...]
    similarity_threshold: float
    lookback_days: int
    max_existing: int
    label: str


def task_dedup_spec() -> DedupSpec:
    """Never `urgency` among the fillable fields: it always has a value ("medium" by
    default on both tasks and extracted candidates), so it's never blank. `goal_id` is
    fillable: a confident AI link can fill an unlinked open task, unless the user set or
    cleared its link by hand."""
    return DedupSpec(
        model=Task,
        crud=crud_tasks,
        fillable_fields=("due_date", "description", "effort_level", "goal_id"),
        sticky_flags=TASK_STICKY_FLAGS,
        live_statuses=("open",),
        closed_statuses=("done",),
        similarity_threshold=settings.TASK_DEDUP_SIMILARITY_THRESHOLD,
        lookback_days=settings.TASK_DEDUP_LOOKBACK_DAYS,
        max_existing=settings.TASK_DEDUP_MAX_EXISTING_TASKS,
        label="task",
    )


def goal_dedup_spec() -> DedupSpec:
    """A paused goal is still a goal the user has, so it's always in the pool (skipped on a
    match, but never filled — only open matches are filled). A dropped goal is treated like
    a done one: in the pool for the lookback window (decisions-log.md 2026-09-24)."""
    return DedupSpec(
        model=Goal,
        crud=crud_goals,
        fillable_fields=("description", "horizon", "target_date"),
        sticky_flags=GOAL_STICKY_FLAGS,
        live_statuses=("open", "paused"),
        closed_statuses=("done", "dropped"),
        similarity_threshold=settings.GOAL_DEDUP_SIMILARITY_THRESHOLD,
        lookback_days=settings.GOAL_DEDUP_LOOKBACK_DAYS,
        max_existing=settings.GOAL_DEDUP_MAX_EXISTING_GOALS,
        label="goal",
    )


async def load_dedup_pool(db: AsyncSession, spec: DedupSpec, user_id: uuid_pkg.UUID) -> list[dict[str, Any]]:
    """The user's live items, plus closed/deleted ones from the last `lookback_days`.
    Plain SQLAlchemy, not FastCRUD — the OR spans several columns, which FastCRUD's
    per-column `__or` can't express. The one read of these tables that includes deleted
    rows on purpose."""
    model = spec.model
    cutoff = datetime.now(UTC) - timedelta(days=spec.lookback_days)
    flag_columns = [spec.sticky_flags[field] for field in spec.fillable_fields if field in spec.sticky_flags]
    columns = [
        getattr(model, name) for name in ("id", "title", "status", "is_deleted", *spec.fillable_fields, *flag_columns)
    ]
    stmt = (
        select(*columns)
        .where(
            model.user_id == user_id,
            or_(
                and_(model.is_deleted.is_(False), model.status.in_(spec.live_statuses)),
                and_(model.is_deleted.is_(False), model.status.in_(spec.closed_statuses), model.updated_at >= cutoff),
                and_(model.is_deleted.is_(True), model.deleted_at >= cutoff),
            ),
        )
        .order_by(model.created_at.desc())
        .limit(spec.max_existing)
    )
    result = await db.execute(stmt)
    pool = [dict(row) for row in result.mappings().all()]
    if len(pool) >= spec.max_existing:
        logger.warning(
            f"{spec.label.capitalize()} dedup pool for user {user_id} hit the {spec.max_existing}-item cap; "
            f"older {spec.label}s were not compared."
        )
    return pool


def _blank_fields(spec: DedupSpec, target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Fields empty on `target` (and not sticky there) that `source` has a value for."""
    blanks = {}
    for field in spec.fillable_fields:
        flag = spec.sticky_flags.get(field)
        if flag and target.get(flag):
            continue
        if not target.get(field) and source.get(field):
            blanks[field] = source[field]
    return blanks


def merge_candidate_duplicates(
    spec: DedupSpec, candidates: list[CandidateT], embeddings: list[list[float]]
) -> list[tuple[CandidateT, list[float]]]:
    """In-memory dedup within one extraction result, before anything is written. Highest
    confidence wins; a dropped duplicate's details fill the kept candidate's blanks."""
    ordered = sorted(zip(candidates, embeddings, strict=True), key=lambda pair: pair[0].confidence, reverse=True)
    kept: list[tuple[CandidateT, list[float]]] = []
    for candidate, embedding in ordered:
        match_index = next(
            (
                index
                for index, (_, kept_embedding) in enumerate(kept)
                if cosine_similarity(embedding, kept_embedding) >= spec.similarity_threshold
            ),
            None,
        )
        if match_index is None:
            kept.append((candidate, embedding))
            continue

        kept_candidate, kept_embedding = kept[match_index]
        blanks = _blank_fields(spec, kept_candidate.model_dump(), candidate.model_dump())
        if blanks:
            kept[match_index] = (kept_candidate.model_copy(update=blanks), kept_embedding)
    return kept


def find_best_match(
    embedding: list[float], pool: list[dict[str, Any]], pool_embeddings: list[list[float]], threshold: float
) -> tuple[dict[str, Any], float] | None:
    """The pool item with the highest similarity, if it clears the threshold."""
    best: tuple[dict[str, Any], float] | None = None
    for item, item_embedding in zip(pool, pool_embeddings, strict=True):
        score = cosine_similarity(embedding, item_embedding)
        if score >= threshold and (best is None or score > best[1]):
            best = (item, score)
    return best


async def fill_blanks(db: AsyncSession, spec: DedupSpec, existing: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Copies only empty, non-sticky `fillable_fields` from `candidate` onto the existing
    open item — never overwrites a filled field. Runs inside the caller's transaction
    (`commit=False`). Updates `existing` in place so a second candidate matching the same
    item in this run sees the fresh values."""
    fields = _blank_fields(spec, existing, candidate)
    if not fields:
        return
    await spec.crud.update(db=db, object=fields, id=existing["id"], commit=False)
    existing.update(fields)


def is_open_match(item: dict[str, Any]) -> bool:
    """Only an open, non-deleted match gets its blanks filled; any other match is just skipped."""
    return item["status"] == "open" and not item["is_deleted"]


async def resolve_candidates(
    db: AsyncSession, spec: DedupSpec, user_id: uuid_pkg.UUID, candidates: list[CandidateT]
) -> list[CandidateT]:
    """Returns only the candidates that should become NEW rows. A near-duplicate of an
    open item fills that item's blanks instead; a near-duplicate of any other pooled item
    (paused goal, recently done/dropped/deleted) is skipped."""
    if not candidates:
        return []

    pool = await load_dedup_pool(db, spec, user_id)
    embeddings = await embed_texts([candidate.title for candidate in candidates] + [item["title"] for item in pool])
    candidate_embeddings, pool_embeddings = embeddings[: len(candidates)], embeddings[len(candidates) :]

    to_create = []
    for candidate, embedding in merge_candidate_duplicates(spec, candidates, candidate_embeddings):
        match = find_best_match(embedding, pool, pool_embeddings, spec.similarity_threshold)
        if match is None:
            to_create.append(candidate)
            continue

        existing, score = match
        if is_open_match(existing):
            await fill_blanks(db, spec, existing, candidate.model_dump())
        logger.info(
            f"Skipped near-duplicate {spec.label} candidate (similarity {score:.3f}) of {spec.label} {existing['id']}"
        )
    return to_create
