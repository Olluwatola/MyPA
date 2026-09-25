"""Background AI guess for a manually-created goal's empty `horizon` (decisions-log.md
2026-09-24). `POST /goals` saves right away and enqueues this job only when the user left
horizon empty. If the AI call keeps failing, horizon simply stays empty.
"""

import uuid as uuid_pkg
from typing import Any

from arq import Retry
from sqlalchemy.exc import NoResultFound

from ...crud.crud_goals import crud_goals
from ..db.database import local_session
from ..integrations.jobs import _retry_delay_seconds
from ..llm.goal_horizon_guess import call_goal_horizon_guess_llm
from ..logger import logging

logger = logging.getLogger(__name__)

GOAL_HORIZON_GUESS_MAX_TRIES = 3


async def guess_goal_horizon(ctx: dict[str, Any], goal_id: str) -> None:
    """Never overwrites a horizon the user set meanwhile. A plain uncaught exception is
    never retried by ARQ, so an LLM failure raises `arq.Retry` with backoff, bounded by
    `GOAL_HORIZON_GUESS_MAX_TRIES` (core/worker.py)."""
    async with local_session() as db:
        goal = await crud_goals.get(db=db, id=uuid_pkg.UUID(goal_id), is_deleted=False)
        if not goal:
            return  # deleted meanwhile
        if goal["horizon"] is not None:
            return  # the user already set it by hand

        try:
            guess = await call_goal_horizon_guess_llm(goal["title"], goal["description"], goal["target_date"])
        except Exception as exc:
            logger.exception(f"Goal horizon guess failed for goal {goal_id}; retrying.")
            raise Retry(defer=_retry_delay_seconds(ctx.get("job_try", 1))) from exc

        if guess.horizon is None:
            return
        # `horizon=None` is part of the WHERE clause, so a value the user set while the LLM
        # was thinking can't be overwritten — no read-then-write gap. No sticky flag needed.
        still_empty: dict[str, Any] = {"horizon": None}
        try:
            await crud_goals.update(
                db=db, object={"horizon": guess.horizon}, id=goal["id"], is_deleted=False, **still_empty
            )
        except NoResultFound:
            return
