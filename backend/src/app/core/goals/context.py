"""The user's OPEN goals, as given to reasoning: chat replies, the extraction and Notion
prompts (for AI task -> goal linking), and Notion goal resolution. This module is the one
place the rule "paused, dropped, done and deleted goals are left out of reasoning" lives
(decisions-log.md 2026-09-24).

Prompts list goals with short numbers (`[1] ...`), not UUIDs — LLMs copy a small number
reliably but often garble a 36-character id. `resolve_goal_link` maps the number back.
"""

import uuid as uuid_pkg
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.goal import Goal
from ..config import settings
from ..logger import logging

logger = logging.getLogger(__name__)


async def load_open_goals(db: AsyncSession, user_id: uuid_pkg.UUID) -> list[dict[str, Any]]:
    """Newest first, capped at `GOAL_CONTEXT_MAX_OPEN_GOALS` so every prompt that carries
    the list has a bounded size."""
    limit = settings.GOAL_CONTEXT_MAX_OPEN_GOALS
    stmt = (
        select(Goal.id, Goal.title, Goal.description, Goal.horizon)
        .where(Goal.user_id == user_id, Goal.status == "open", Goal.is_deleted.is_(False))
        .order_by(Goal.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    goals = [dict(row) for row in result.mappings().all()]
    if len(goals) >= limit:
        logger.warning(f"Open goals for user {user_id} hit the {limit}-goal context cap; older goals were left out.")
    return goals


def _horizon_label(goal: dict[str, Any]) -> str:
    return f" ({goal['horizon'].replace('_', ' ')})" if goal.get("horizon") else ""


def format_goals_for_prompt(goals: list[dict[str, Any]]) -> str:
    """Numbered list for prompts that may link a task to a goal: `[1] Launch ClientPal
    (short term)`. Empty string for no goals."""
    return "\n".join(f"[{number}] {goal['title']}{_horizon_label(goal)}" for number, goal in enumerate(goals, start=1))


def format_goals_for_chat(goals: list[dict[str, Any]]) -> str:
    """Plain bullet list for the chat reply — it never refers back to a goal by number."""
    return "\n".join(f"- {goal['title']}{_horizon_label(goal)}" for goal in goals)


def resolve_goal_link(
    goal_ref: int | None, goal_link_confidence: float | None, goals: list[dict[str, Any]]
) -> uuid_pkg.UUID | None:
    """The one rule for a "confident" AI task -> goal link (decisions-log.md 2026-09-24):
    the number must be one the LLM was actually shown, and its own score must reach
    `TASK_GOAL_LINK_CONFIDENCE_THRESHOLD`. Anything else means no link — an unsure link is
    never saved (the Yes/No question is Feature 1.11)."""
    if goal_ref is None or goal_link_confidence is None:
        return None
    if not 1 <= goal_ref <= len(goals):
        return None
    if goal_link_confidence < settings.TASK_GOAL_LINK_CONFIDENCE_THRESHOLD:
        return None
    goal_id: uuid_pkg.UUID = goals[goal_ref - 1]["id"]
    return goal_id
