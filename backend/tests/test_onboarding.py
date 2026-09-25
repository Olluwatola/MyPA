"""Unit tests for the onboarding trigger helper and the three onboarding routes: the
shared trigger (used by both the OAuth callback and the resume endpoint), status polling
(a raw pass-through of `get_current_user`'s dict), and goal-suggestion submission (source
mapping per list, the `ready`-only gate, and the zero-items case)."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.api.v1.onboarding import OnboardingGoalsSubmitRequest, get_onboarding_status, submit_onboarding_goals
from src.app.core.exceptions.http_exceptions import BadRequestException
from src.app.core.integrations.onboarding import trigger_onboarding_run
from src.app.schemas.goal import SuggestedGoal

ONBOARDING_HELPER_MODULE = "src.app.core.integrations.onboarding"
ROUTE_MODULE = "src.app.api.v1.onboarding"


class TestTriggerOnboardingRun:
    @pytest.mark.asyncio
    async def test_sets_pending_clears_suggestions_and_enqueues(self, mock_db):
        user_id = uuid7()

        with (
            patch(f"{ONBOARDING_HELPER_MODULE}.crud_users") as mock_crud,
            patch(f"{ONBOARDING_HELPER_MODULE}.queue") as mock_queue,
        ):
            mock_crud.update = AsyncMock()
            mock_queue.pool.enqueue_job = AsyncMock()

            await trigger_onboarding_run(mock_db, user_id)

        mock_crud.update.assert_called_once_with(
            db=mock_db, object={"onboarding_status": "pending", "onboarding_suggested_goals": None}, id=user_id
        )
        mock_queue.pool.enqueue_job.assert_called_once_with("run_onboarding_ingestion", str(user_id))


class TestGetOnboardingStatus:
    @pytest.mark.asyncio
    async def test_returns_current_user_dict_unchanged(self, current_user_dict):
        current_user_dict["onboarding_status"] = "ready"
        current_user_dict["onboarding_suggested_goals"] = [{"title": "Finish the report"}]
        current_user_dict["onboarding_completed_at"] = None

        result = await get_onboarding_status(current_user=current_user_dict)

        assert result is current_user_dict


class TestSubmitOnboardingGoals:
    @pytest.mark.asyncio
    async def test_rejects_when_not_ready(self, mock_db, current_user_dict):
        current_user_dict["onboarding_status"] = "pending"
        payload = OnboardingGoalsSubmitRequest()

        with pytest.raises(BadRequestException):
            await submit_onboarding_goals(payload=payload, current_user=current_user_dict, db=mock_db)

    @pytest.mark.asyncio
    async def test_maps_source_per_list_and_marks_completed(self, mock_db, current_user_dict):
        current_user_dict["onboarding_status"] = "ready"
        payload = OnboardingGoalsSubmitRequest(
            checked_suggestions=[SuggestedGoal(title="Finish the Q3 report", horizon="short_term")],
            additional_goals=[SuggestedGoal(title="Learn Spanish")],
        )

        with (
            patch(f"{ROUTE_MODULE}.crud_goals") as mock_goals_crud,
            patch(f"{ROUTE_MODULE}.crud_users") as mock_users_crud,
            patch(
                f"{ROUTE_MODULE}.resolve_checked_suggestions",
                new=AsyncMock(side_effect=lambda db, user_id, suggestions: suggestions),
            ),
        ):
            mock_goals_crud.create = AsyncMock(side_effect=[{"id": uuid7()}, {"id": uuid7()}])
            mock_users_crud.update = AsyncMock()

            created = await submit_onboarding_goals(payload=payload, current_user=current_user_dict, db=mock_db)

        assert len(created) == 2
        assert mock_goals_crud.create.call_count == 2
        first_call, second_call = mock_goals_crud.create.call_args_list
        assert first_call.kwargs["object"].source == "conversation"
        assert first_call.kwargs["object"].title == "Finish the Q3 report"
        assert second_call.kwargs["object"].source == "manual"
        assert second_call.kwargs["object"].title == "Learn Spanish"

        mock_users_crud.update.assert_called_once()
        update_object = mock_users_crud.update.call_args.kwargs["object"]
        assert update_object["onboarding_status"] == "completed"
        assert update_object["onboarding_suggested_goals"] is None
        assert update_object["onboarding_completed_at"] is not None
        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_items_is_valid_and_still_completes(self, mock_db, current_user_dict):
        current_user_dict["onboarding_status"] = "ready"
        payload = OnboardingGoalsSubmitRequest()

        with (
            patch(f"{ROUTE_MODULE}.crud_goals") as mock_goals_crud,
            patch(f"{ROUTE_MODULE}.crud_users") as mock_users_crud,
            patch(f"{ROUTE_MODULE}.resolve_checked_suggestions", new=AsyncMock(return_value=[])),
        ):
            mock_goals_crud.create = AsyncMock()
            mock_users_crud.update = AsyncMock()

            created = await submit_onboarding_goals(payload=payload, current_user=current_user_dict, db=mock_db)

        assert created == []
        mock_goals_crud.create.assert_not_called()
        mock_users_crud.update.assert_called_once()
        assert mock_users_crud.update.call_args.kwargs["object"]["onboarding_status"] == "completed"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_checked_suggestion_the_user_already_has_is_not_created(self, mock_db, current_user_dict):
        """Required proof (e), submit half: a checked suggestion matching an existing goal
        is skipped; a typed goal with the same title is still created (not deduped)."""
        current_user_dict["onboarding_status"] = "ready"
        duplicate = SuggestedGoal(title="Close the seed round")
        payload = OnboardingGoalsSubmitRequest(
            checked_suggestions=[duplicate], additional_goals=[SuggestedGoal(title="Close the seed round")]
        )

        with (
            patch(f"{ROUTE_MODULE}.crud_goals") as mock_goals_crud,
            patch(f"{ROUTE_MODULE}.crud_users") as mock_users_crud,
            patch(f"{ROUTE_MODULE}.resolve_checked_suggestions", new=AsyncMock(return_value=[])) as mock_resolve,
        ):
            mock_goals_crud.create = AsyncMock(return_value={"id": uuid7()})
            mock_users_crud.update = AsyncMock()

            created = await submit_onboarding_goals(payload=payload, current_user=current_user_dict, db=mock_db)

        assert mock_resolve.call_args.args[1:] == (current_user_dict["id"], [duplicate])
        assert len(created) == 1
        assert mock_goals_crud.create.call_args.kwargs["object"].source == "manual"
        mock_db.commit.assert_called_once()
