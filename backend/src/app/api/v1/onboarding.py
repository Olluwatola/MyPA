"""Onboarding: bulk-ingestion kickoff/resume, status polling, and goal-suggestion
submission. See `core/integrations/onboarding.py` for the shared trigger helper both
`run_onboarding` and the OAuth callback call, and `core/integrations/jobs.py` for the
actual bulk-ingestion job."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import BadRequestException
from ...core.integrations.onboarding import trigger_onboarding_run
from ...crud.crud_goals import crud_goals
from ...crud.crud_users import crud_users
from ...schemas.goal import GoalCreateInternal, GoalRead, SuggestedGoal
from ...schemas.user import OnboardingStatusRead
from ..dependencies import get_current_user

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class OnboardingGoalsSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_suggestions: list[SuggestedGoal] = Field(default_factory=list)
    additional_goals: list[SuggestedGoal] = Field(default_factory=list)


@router.post("/run", response_model=OnboardingStatusRead, status_code=202)
async def run_onboarding(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    """Same action serves the first automatic run (fired from the OAuth callback) and any
    later resume — always regenerates and overwrites the prior suggestion set."""
    await trigger_onboarding_run(db, current_user["id"])
    return {"onboarding_status": "pending", "onboarding_suggested_goals": None, "onboarding_completed_at": None}


@router.get("/status", response_model=OnboardingStatusRead, status_code=200)
async def get_onboarding_status(current_user: Annotated[dict, Depends(get_current_user)]) -> dict[str, Any]:
    """`get_current_user` already returns the full raw dict including the three
    onboarding columns — no extra DB round trip needed."""
    return current_user


@router.post("/goals", response_model=list[GoalRead], status_code=201)
async def submit_onboarding_goals(
    payload: OnboardingGoalsSubmitRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> list[dict[str, Any]]:
    """Zero items in both lists is valid (onboarding is optional per-item) — still marks
    `completed`. `memory_record_id` stays `NULL` for every suggestion-derived goal —
    synthesis spans many extraction records, not one FK-able one."""
    if current_user["onboarding_status"] != "ready":
        raise BadRequestException("Onboarding is not ready for goal submission.")

    created: list[dict[str, Any]] = []
    try:
        for suggestion in payload.checked_suggestions:
            created.append(
                await crud_goals.create(
                    db=db,
                    object=GoalCreateInternal(
                        user_id=current_user["id"],
                        title=suggestion.title,
                        description=suggestion.description,
                        horizon=suggestion.horizon,
                        source="conversation",
                    ),
                    schema_to_select=GoalRead,
                    commit=False,
                )
            )
        for extra in payload.additional_goals:
            created.append(
                await crud_goals.create(
                    db=db,
                    object=GoalCreateInternal(
                        user_id=current_user["id"],
                        title=extra.title,
                        description=extra.description,
                        horizon=extra.horizon,
                        source="manual",
                    ),
                    schema_to_select=GoalRead,
                    commit=False,
                )
            )

        await crud_users.update(
            db=db,
            object={
                "onboarding_status": "completed",
                "onboarding_suggested_goals": None,
                "onboarding_completed_at": datetime.now(UTC),
            },
            id=current_user["id"],
        )
    except Exception:
        await db.rollback()
        raise

    await db.commit()
    return created
