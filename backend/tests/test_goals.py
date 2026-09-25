"""Unit tests for the goal CRUD routes (api/v1/goals.py) — mirrors test_tasks.py: source
forced to "manual", background horizon guess only when horizon is empty, list filters/
sort/pagination, sticky title/description on manual edit, soft delete (never touching
Notion, un-linking the goal's tasks), soft-deleted goals returning 404 on every
single-item route, and the D-06 fix on the status route."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from uuid6 import uuid7

from src.app.api.v1.goals import (
    GoalStatusUpdate,
    erase_goal,
    patch_goal,
    patch_goal_status,
    read_goal,
    read_goals,
    write_goal,
)
from src.app.core.exceptions.http_exceptions import ForbiddenException, NotFoundException
from src.app.schemas.goal import GoalCreate, GoalUpdate

MODULE = "src.app.api.v1.goals"


def _owned_goal(current_user_dict: dict, **overrides) -> dict:
    return {
        "id": uuid7(),
        "user_id": current_user_dict["id"],
        "status": "open",
        "title": "Launch ClientPal",
    } | overrides


def _assert_lookup_hides_deleted(mock_crud) -> None:
    assert mock_crud.get.call_args.kwargs["is_deleted"] is False


class TestWriteGoal:
    @pytest.mark.asyncio
    async def test_source_forced_to_manual(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.create = AsyncMock(return_value={"id": uuid7()})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_goal(
                body=GoalCreate(title="Launch ClientPal", horizon="short_term", target_date=date(2027, 3, 1)),
                current_user=current_user_dict,
                db=mock_db,
            )

        created = mock_crud.create.call_args.kwargs["object"]
        assert created.source == "manual"
        assert created.user_id == current_user_dict["id"]
        assert created.target_date == date(2027, 3, 1)

    def test_client_cannot_send_source_or_due_date(self):
        with pytest.raises(ValidationError):
            GoalCreate(title="Launch ClientPal", source="email")  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            GoalCreate(title="Launch ClientPal", due_date="2027-01-01")  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_horizon_given_means_no_guess(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.create = AsyncMock(return_value={"id": uuid7()})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_goal(
                body=GoalCreate(title="Run a marathon", horizon="long_term"), current_user=current_user_dict, db=mock_db
            )
        mock_queue.pool.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_horizon_enqueues_guess(self, mock_db, current_user_dict):
        goal_id = uuid7()
        with patch(f"{MODULE}.crud_goals") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.create = AsyncMock(return_value={"id": goal_id})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_goal(body=GoalCreate(title="Run a marathon"), current_user=current_user_dict, db=mock_db)

        assert mock_crud.create.call_args.kwargs["object"].horizon is None
        mock_queue.pool.enqueue_job.assert_called_once_with("guess_goal_horizon", str(goal_id))


class TestReadGoals:
    @pytest.mark.asyncio
    async def test_default_call_filters_deleted_sorts_newest_first_and_paginates(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get_multi = AsyncMock(return_value={"data": [], "total_count": 45})
            result = await read_goals(current_user=current_user_dict, db=mock_db, page=2, items_per_page=20)

        kwargs = mock_crud.get_multi.call_args.kwargs
        assert kwargs["user_id"] == current_user_dict["id"]
        assert kwargs["is_deleted"] is False
        assert kwargs["offset"] == 20 and kwargs["limit"] == 20
        assert kwargs["sort_columns"] == ["created_at", "id"]
        assert kwargs["sort_orders"] == ["desc", "desc"]
        assert "status__in" not in kwargs and "horizon" not in kwargs and "source" not in kwargs
        assert result == {"data": [], "total_count": 45, "has_more": True, "page": 2, "items_per_page": 20}

    @pytest.mark.asyncio
    async def test_filters_are_passed_through_and_status_takes_several_values(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get_multi = AsyncMock(return_value={"data": [], "total_count": 0})
            await read_goals(
                current_user=current_user_dict,
                db=mock_db,
                status=["open", "paused"],
                horizon="short_term",
                source="email",
            )

        kwargs = mock_crud.get_multi.call_args.kwargs
        assert kwargs["status__in"] == ["open", "paused"]
        assert kwargs["horizon"] == "short_term"
        assert kwargs["source"] == "email"


class TestReadGoal:
    @pytest.mark.asyncio
    async def test_returns_owned_goal(self, mock_db, current_user_dict):
        goal = _owned_goal(current_user_dict)
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=goal)
            assert await read_goal(goal_id=goal["id"], current_user=current_user_dict, db=mock_db) == goal
        _assert_lookup_hides_deleted(mock_crud)

    @pytest.mark.asyncio
    async def test_deleted_goal_404(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundException):
                await read_goal(goal_id=uuid7(), current_user=current_user_dict, db=mock_db)
        _assert_lookup_hides_deleted(mock_crud)

    @pytest.mark.asyncio
    async def test_other_users_goal_403(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=_owned_goal(current_user_dict, user_id=uuid7()))
            with pytest.raises(ForbiddenException):
                await read_goal(goal_id=uuid7(), current_user=current_user_dict, db=mock_db)


class TestPatchGoal:
    async def _patch(self, mock_db, current_user_dict, body):
        goal = _owned_goal(current_user_dict)
        with patch(f"{MODULE}.crud_goals") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.get = AsyncMock(return_value=goal)
            mock_crud.update = AsyncMock(return_value={"id": goal["id"]})
            mock_queue.pool.enqueue_job = AsyncMock()
            result = await patch_goal(goal_id=goal["id"], body=body, current_user=current_user_dict, db=mock_db)
        return result, mock_crud, mock_queue

    @pytest.mark.parametrize(
        ("field", "value", "flag"),
        [("title", "Launch ClientPal v2", "title_manually_set"), ("description", "Public", "description_manually_set")],
    )
    @pytest.mark.asyncio
    async def test_editing_a_sticky_field_sets_only_its_flag(self, mock_db, current_user_dict, field, value, flag):
        _, mock_crud, _ = await self._patch(mock_db, current_user_dict, GoalUpdate(**{field: value}))
        assert mock_crud.update.call_args.kwargs["object"] == {field: value, flag: True}

    @pytest.mark.asyncio
    async def test_horizon_and_target_date_set_no_flag(self, mock_db, current_user_dict):
        body = GoalUpdate(horizon="long_term", target_date=date(2027, 6, 1))
        _, mock_crud, _ = await self._patch(mock_db, current_user_dict, body)
        assert mock_crud.update.call_args.kwargs["object"] == {"horizon": "long_term", "target_date": date(2027, 6, 1)}

    @pytest.mark.asyncio
    async def test_clearing_description_is_a_manual_edit(self, mock_db, current_user_dict):
        _, mock_crud, _ = await self._patch(mock_db, current_user_dict, GoalUpdate(description=None))
        assert mock_crud.update.call_args.kwargs["object"] == {
            "description": None,
            "description_manually_set": True,
        }

    @pytest.mark.asyncio
    async def test_update_returns_the_row_and_hides_deleted(self, mock_db, current_user_dict):
        result, mock_crud, _ = await self._patch(mock_db, current_user_dict, GoalUpdate(title="x"))
        kwargs = mock_crud.update.call_args.kwargs
        assert kwargs["return_as_model"] is True and kwargs["is_deleted"] is False
        assert result is not None

    def test_explicit_null_title_rejected(self):
        with pytest.raises(ValidationError):
            GoalUpdate(title=None)

    def test_status_not_accepted(self):
        with pytest.raises(ValidationError):
            GoalUpdate(status="done")  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_empty_body_writes_nothing(self, mock_db, current_user_dict):
        _, mock_crud, _ = await self._patch(mock_db, current_user_dict, GoalUpdate())
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_notion_sync_enqueued(self, mock_db, current_user_dict):
        _, _, mock_queue = await self._patch(mock_db, current_user_dict, GoalUpdate(title="x"))
        mock_queue.pool.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_deleted_goal_404(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            mock_crud.update = AsyncMock()
            with pytest.raises(NotFoundException):
                await patch_goal(
                    goal_id=uuid7(), body=GoalUpdate(title="x"), current_user=current_user_dict, db=mock_db
                )
        _assert_lookup_hides_deleted(mock_crud)
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_users_goal_403(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=_owned_goal(current_user_dict, user_id=uuid7()))
            with pytest.raises(ForbiddenException):
                await patch_goal(
                    goal_id=uuid7(), body=GoalUpdate(title="x"), current_user=current_user_dict, db=mock_db
                )


class TestEraseGoal:
    @pytest.mark.asyncio
    async def test_soft_deletes_unlinks_tasks_and_never_touches_notion(self, mock_db, current_user_dict):
        goal = _owned_goal(current_user_dict)
        mock_db.execute = AsyncMock()
        with (
            patch(f"{MODULE}.crud_goals") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=goal)
            mock_crud.delete = AsyncMock()
            mock_crud.db_delete = AsyncMock()
            mock_queue.pool.enqueue_job = AsyncMock()
            result = await erase_goal(goal_id=goal["id"], current_user=current_user_dict, db=mock_db)

        assert result == {"message": "Goal deleted."}
        mock_crud.delete.assert_called_once_with(db=mock_db, id=goal["id"])
        mock_crud.db_delete.assert_not_called()
        mock_queue.pool.enqueue_job.assert_not_called()

        # tasks pointing at this goal are un-linked (soft delete doesn't fire ON DELETE SET NULL)
        stmt = mock_db.execute.call_args.args[0]
        sql = str(stmt.compile())
        assert sql.startswith("UPDATE tasks SET goal_id=")
        assert "WHERE tasks.goal_id = :goal_id_1" in sql
        params = stmt.compile().params
        assert params["goal_id"] is None and params["goal_id_1"] == goal["id"]

    @pytest.mark.asyncio
    async def test_already_deleted_404(self, mock_db, current_user_dict):
        mock_db.execute = AsyncMock()
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            mock_crud.delete = AsyncMock()
            with pytest.raises(NotFoundException):
                await erase_goal(goal_id=uuid7(), current_user=current_user_dict, db=mock_db)
        _assert_lookup_hides_deleted(mock_crud)
        mock_crud.delete.assert_not_called()
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_users_goal_403(self, mock_db, current_user_dict):
        mock_db.execute = AsyncMock()
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=_owned_goal(current_user_dict, user_id=uuid7()))
            mock_crud.delete = AsyncMock()
            with pytest.raises(ForbiddenException):
                await erase_goal(goal_id=uuid7(), current_user=current_user_dict, db=mock_db)
        mock_crud.delete.assert_not_called()


class TestPatchGoalStatus:
    @pytest.mark.asyncio
    async def test_missing_goal_raises_not_found(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundException):
                await patch_goal_status(
                    goal_id=uuid7(), body=GoalStatusUpdate(status="done"), current_user=current_user_dict, db=mock_db
                )
        _assert_lookup_hides_deleted(mock_crud)

    @pytest.mark.asyncio
    async def test_other_users_goal_raises_forbidden(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_goals") as mock_crud:
            mock_crud.get = AsyncMock(return_value=_owned_goal(current_user_dict, user_id=uuid7()))
            with pytest.raises(ForbiddenException):
                await patch_goal_status(
                    goal_id=uuid7(), body=GoalStatusUpdate(status="done"), current_user=current_user_dict, db=mock_db
                )

    @pytest.mark.parametrize("status", ["open", "paused", "done", "dropped"])
    @pytest.mark.asyncio
    async def test_returns_updated_goal_and_enqueues_notion_sync(self, mock_db, current_user_dict, status):
        """Required proof (i) / the D-06 fix: `return_as_model=True` is what makes FastCRUD
        return the row at all — without it the route returned None and 500'd."""
        goal = _owned_goal(current_user_dict)
        with (
            patch(f"{MODULE}.crud_goals") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=goal)
            mock_crud.update = AsyncMock(return_value={"id": goal["id"], "status": status})
            mock_queue.pool.enqueue_job = AsyncMock()

            result = await patch_goal_status(
                goal_id=goal["id"], body=GoalStatusUpdate(status=status), current_user=current_user_dict, db=mock_db
            )

        assert result == {"id": goal["id"], "status": status}
        kwargs = mock_crud.update.call_args.kwargs
        assert kwargs["object"] == {"status": status}
        assert kwargs["return_as_model"] is True
        mock_queue.pool.enqueue_job.assert_called_once_with("sync_status_to_notion", "goal", str(goal["id"]))

    def test_unknown_status_rejected(self):
        with pytest.raises(ValidationError):
            GoalStatusUpdate(status="archived")  # type: ignore[arg-type]
