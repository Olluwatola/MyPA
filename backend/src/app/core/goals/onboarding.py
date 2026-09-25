"""Onboarding goal suggestions must never offer, or create, a goal the user already has
(decisions-log.md 2026-09-24). Checked in two places:

1. `drop_existing_goal_suggestions` — in the onboarding job, right after synthesis, so the
   checklist never shows a goal the user has. This matters because the same onboarding run
   auto-creates confident email goals through the extraction pipeline first.
2. `resolve_checked_suggestions` — in `POST /onboarding/goals`, because minutes can pass
   between synthesis and submit (a chat message could create the same goal meanwhile), and
   the client posts the suggestions back, so they can't be trusted as-is.

Same goal pool and threshold as chat/email dedup (`goal_dedup_spec()`). Built on the
lower-level dedup functions rather than `resolve_candidates`, since a suggestion has no
confidence score to order by.
"""

import uuid as uuid_pkg
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...schemas.goal import SuggestedGoal
from ..items.dedup import fill_blanks, find_best_match, goal_dedup_spec, is_open_match, load_dedup_pool
from ..llm.embedding_model import embed_texts


async def _match_suggestions(
    db: AsyncSession, user_id: uuid_pkg.UUID, suggestions: list[SuggestedGoal]
) -> list[tuple[SuggestedGoal, dict[str, Any] | None]]:
    """Each suggestion paired with the existing goal it duplicates, or `None`."""
    if not suggestions:
        return []
    spec = goal_dedup_spec()
    pool = await load_dedup_pool(db, spec, user_id)
    if not pool:
        return [(suggestion, None) for suggestion in suggestions]

    embeddings = await embed_texts([s.title for s in suggestions] + [goal["title"] for goal in pool])
    suggestion_embeddings, pool_embeddings = embeddings[: len(suggestions)], embeddings[len(suggestions) :]
    paired: list[tuple[SuggestedGoal, dict[str, Any] | None]] = []
    for suggestion, embedding in zip(suggestions, suggestion_embeddings, strict=True):
        match = find_best_match(embedding, pool, pool_embeddings, spec.similarity_threshold)
        paired.append((suggestion, match[0] if match else None))
    return paired


async def drop_existing_goal_suggestions(
    db: AsyncSession, user_id: uuid_pkg.UUID, suggestions: list[SuggestedGoal]
) -> list[SuggestedGoal]:
    """Suggestions that don't duplicate any pooled goal. No writes."""
    return [suggestion for suggestion, match in await _match_suggestions(db, user_id, suggestions) if match is None]


async def resolve_checked_suggestions(
    db: AsyncSession, user_id: uuid_pkg.UUID, suggestions: list[SuggestedGoal]
) -> list[SuggestedGoal]:
    """Only the checked suggestions that should become NEW goals. An open match gets its
    blanks filled (`commit=False` — joins the caller's transaction); any other match is
    skipped."""
    spec = goal_dedup_spec()
    to_create = []
    for suggestion, match in await _match_suggestions(db, user_id, suggestions):
        if match is None:
            to_create.append(suggestion)
        elif is_open_match(match):
            await fill_blanks(db, spec, match, suggestion.model_dump())
    return to_create
