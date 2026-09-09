"""Shared trigger helper so both the OAuth callback (first automatic run) and the resume
endpoint (`POST /onboarding/run`) call the literal same code, not a duplicated snippet."""

import uuid as uuid_pkg

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_users import crud_users
from ..utils import queue


async def trigger_onboarding_run(db: AsyncSession, user_id: uuid_pkg.UUID) -> None:
    """Unconditional — same action for the very first run (fired from the OAuth callback) and
    any later resume (fired from POST /onboarding/run). Clears any prior suggestion set
    immediately so a status check mid-refresh doesn't show stale 'ready' suggestions."""
    await crud_users.update(
        db=db, object={"onboarding_status": "pending", "onboarding_suggested_goals": None}, id=user_id
    )
    await queue.pool.enqueue_job("run_onboarding_ingestion", str(user_id))  # type: ignore[union-attr]
