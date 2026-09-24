"""Background AI guess for a manually-created task's empty `urgency`/`effort_level`
(decisions-log.md 2026-09-24). `POST /tasks` saves right away with defaults
(`urgency="medium"`, `effort_level=None`) and enqueues this job for the field(s) the user
left empty. If the AI call keeps failing, the defaults simply stay.
"""

import uuid as uuid_pkg
from typing import Any

from arq import Retry
from sqlalchemy.exc import NoResultFound

from ...crud.crud_tasks import crud_tasks
from ..db.database import local_session
from ..integrations.jobs import _retry_delay_seconds
from ..llm.task_field_guess import call_task_field_guess_llm
from ..logger import logging
from .sticky import STICKY_FLAG_BY_FIELD

logger = logging.getLogger(__name__)

TASK_FIELD_GUESS_MAX_TRIES = 3


async def guess_task_fields(ctx: dict[str, Any], task_id: str, fields: list[str]) -> None:
    """Only ever fills requested fields whose sticky flag is still unset. A plain uncaught
    exception is never retried by ARQ, so an LLM failure raises `arq.Retry` with backoff,
    bounded by `TASK_FIELD_GUESS_MAX_TRIES` (core/worker.py)."""
    async with local_session() as db:
        task = await crud_tasks.get(db=db, id=uuid_pkg.UUID(task_id), is_deleted=False)
        if not task:
            return  # deleted meanwhile

        still_needed = [field for field in fields if not task[STICKY_FLAG_BY_FIELD[field]]]
        if not still_needed:
            return  # the user already set every requested field by hand

        try:
            guess = await call_task_field_guess_llm(task["title"], task["description"], task["due_date"], still_needed)
        except Exception as exc:
            logger.exception(f"Task field guess failed for task {task_id}; retrying.")
            raise Retry(defer=_retry_delay_seconds(ctx.get("job_try", 1))) from exc

        for field in still_needed:
            value = getattr(guess, field)
            if value is None:
                continue
            # The sticky flag is part of the WHERE clause, so a user edit that landed while
            # the LLM was thinking can't be overwritten — no read-then-write gap. The guess
            # itself never sets the flag.
            flag_still_unset: dict[str, Any] = {STICKY_FLAG_BY_FIELD[field]: False}
            try:
                await crud_tasks.update(
                    db=db, object={field: value}, id=task["id"], is_deleted=False, **flag_still_unset
                )
            except NoResultFound:
                continue
