"""'Insufficient context' resolution against existing goals (PRD §5.6 step 6) — fixed,
sequential code that calls the existing retrieval function, NOT a model-callable tool.
Every LLM call in this feature is single-shot (confirmed 2026-09-23); the model never
decides mid-task to go look something up itself.
"""

import uuid as uuid_pkg

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_embeddings import crud_embeddings
from ...crud.crud_goals import crud_goals
from ..config import settings
from ..llm.embedding_model import embed_text
from ..llm.retrieval import search_similar_memories
from ..llm.similarity import cosine_similarity


async def resolve_against_existing_goals(
    db: AsyncSession, user_id: uuid_pkg.UUID, block_summary: str
) -> uuid_pkg.UUID | None:
    """Returns the best-matching Goal's id only if its similarity clears both an
    absolute threshold AND a margin over the runner-up (guards the ambiguous
    multi-plausible-goal case, which per the PRD should escalate, not guess). Returns
    `None` (ambiguous/empty) otherwise — the caller then escalates a clarifying question."""
    candidates = await search_similar_memories(db, user_id, block_summary, top_k=3)
    if not candidates:
        return None

    query_vector = await embed_text(block_summary)

    scored: list[tuple[float, uuid_pkg.UUID]] = []
    for record in candidates:
        goal = await crud_goals.get(db=db, memory_record_id=record.id)
        if not goal:
            continue
        embedding_row = await crud_embeddings.get(db=db, memory_record_id=record.id)
        if not embedding_row:
            continue
        similarity = cosine_similarity(query_vector, list(embedding_row["embedding"]))
        scored.append((similarity, goal["id"]))

    if not scored:
        return None

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_similarity, best_goal_id = scored[0]
    if best_similarity < settings.NOTION_GOAL_RESOLUTION_SIMILARITY_THRESHOLD:
        return None

    if len(scored) > 1:
        runner_up_similarity = scored[1][0]
        if best_similarity - runner_up_similarity < settings.NOTION_GOAL_RESOLUTION_MARGIN:
            return None

    return best_goal_id
