"""'Insufficient context' resolution against existing goals (PRD §5.6 step 6) — fixed,
sequential code, NOT a model-callable tool. Every LLM call in this feature is single-shot
(confirmed 2026-09-23); the model never decides mid-task to go look something up itself.

Compares the block summary directly against every OPEN goal's title + description, with
embeddings computed on the fly (the same approach as dedup). Before 1.9 this went through
stored memory-record embeddings, so it could only ever match goals that had a
`memory_record_id` — manual, onboarding, chat and email goals were invisible to it
(decisions-log.md 2026-09-24). Paused, dropped, done and deleted goals are never matched.
"""

import uuid as uuid_pkg

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..goals.context import load_open_goals
from ..llm.embedding_model import embed_texts
from ..llm.similarity import cosine_similarity


async def resolve_against_existing_goals(
    db: AsyncSession, user_id: uuid_pkg.UUID, block_summary: str
) -> uuid_pkg.UUID | None:
    """Returns the best-matching Goal's id only if its similarity clears both an
    absolute threshold AND a margin over the runner-up (guards the ambiguous
    multi-plausible-goal case, which per the PRD should escalate, not guess). Returns
    `None` (ambiguous/empty) otherwise — the caller then escalates a clarifying question."""
    goals = await load_open_goals(db, user_id)
    if not goals:
        return None

    embeddings = await embed_texts(
        [block_summary] + [f"{goal['title']}. {goal['description'] or ''}" for goal in goals]
    )
    query_vector, goal_vectors = embeddings[0], embeddings[1:]

    scored = sorted(
        (
            (cosine_similarity(query_vector, vector), goal["id"])
            for goal, vector in zip(goals, goal_vectors, strict=True)
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_similarity, best_goal_id = scored[0]
    if best_similarity < settings.NOTION_GOAL_RESOLUTION_SIMILARITY_THRESHOLD:
        return None

    if len(scored) > 1:
        runner_up_similarity = scored[1][0]
        if best_similarity - runner_up_similarity < settings.NOTION_GOAL_RESOLUTION_MARGIN:
            return None

    goal_id: uuid_pkg.UUID = best_goal_id
    return goal_id
