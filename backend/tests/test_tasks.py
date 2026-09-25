"""Unit tests for the task CRUD routes (api/v1/tasks.py): source forced to "manual",
background AI guess only for empty fields, list filters/sort/pagination, sticky flags on
manual edit, soft delete (never touching Notion), and soft-deleted tasks returning 404 on
every single-item route."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from uuid6 import uuid7

from src.app.api.v1.tasks import (
    TaskStatusUpdate,
    erase_task,
    patch_task,
    patch_task_status,
    read_task,
    read_tasks,
    write_task,
)
from src.app.core.exceptions.http_exceptions import BadRequestException, ForbiddenException, NotFoundException
from src.app.schemas.task import TaskCreate, TaskUpdate

MODULE = "src.app.api.v1.tasks"


def _owned_task(current_user_dict: dict, **overrides) -> dict:
    return {"id": uuid7(), "user_id": current_user_dict["id"], "status": "open", "title": "Send invoice"} | overrides


def _assert_lookup_hides_deleted(mock_crud) -> None:
    assert mock_crud.get.call_args.kwargs["is_deleted"] is False


class TestWriteTask:
    @pytest.mark.asyncio
    async def test_source_forced_to_manual(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.create = AsyncMock(return_value={"id": uuid7()})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_task(
                body=TaskCreate(title="Send invoice", urgency="high", effort_level="light_focus"),
                current_user=current_user_dict,
                db=mock_db,
            )

        created = mock_crud.create.call_args.kwargs["object"]
        assert created.source == "manual"
        assert created.user_id == current_user_dict["id"]

    def test_client_cannot_send_source(self):
        with pytest.raises(ValidationError):
            TaskCreate(title="Send invoice", source="email")  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_filled_fields_are_manual_and_no_guess_enqueued(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.create = AsyncMock(return_value={"id": uuid7()})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_task(
                body=TaskCreate(title="Send invoice", urgency="high", effort_level="deep_focus"),
                current_user=current_user_dict,
                db=mock_db,
            )

        created = mock_crud.create.call_args.kwargs["object"]
        assert created.urgency == "high" and created.urgency_manually_set is True
        assert created.effort_level == "deep_focus" and created.effort_level_manually_set is True
        mock_queue.pool.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_fields_get_defaults_and_guess_job(self, mock_db, current_user_dict):
        task_id = uuid7()
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.create = AsyncMock(return_value={"id": task_id})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_task(body=TaskCreate(title="Send invoice"), current_user=current_user_dict, db=mock_db)

        created = mock_crud.create.call_args.kwargs["object"]
        assert created.urgency == "medium" and created.urgency_manually_set is False
        assert created.effort_level is None and created.effort_level_manually_set is False
        mock_queue.pool.enqueue_job.assert_called_once_with(
            "guess_task_fields", str(task_id), ["urgency", "effort_level"]
        )

    @pytest.mark.asyncio
    async def test_only_the_empty_field_is_guessed(self, mock_db, current_user_dict):
        task_id = uuid7()
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.create = AsyncMock(return_value={"id": task_id})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_task(
                body=TaskCreate(title="Send invoice", urgency="low"), current_user=current_user_dict, db=mock_db
            )

        created = mock_crud.create.call_args.kwargs["object"]
        assert created.urgency_manually_set is True
        assert created.effort_level_manually_set is False
        mock_queue.pool.enqueue_job.assert_called_once_with("guess_task_fields", str(task_id), ["effort_level"])


class TestReadTasks:
    @pytest.mark.asyncio
    async def test_default_call_filters_deleted_sorts_and_paginates(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get_multi = AsyncMock(return_value={"data": [], "total_count": 45})
            result = await read_tasks(current_user=current_user_dict, db=mock_db, page=2, items_per_page=20)

        kwargs = mock_crud.get_multi.call_args.kwargs
        assert kwargs["user_id"] == current_user_dict["id"]
        assert kwargs["is_deleted"] is False
        assert kwargs["offset"] == 20 and kwargs["limit"] == 20
        assert kwargs["sort_columns"] == ["status", "due_date", "created_at", "id"]
        assert kwargs["sort_orders"] == ["desc", "asc", "desc", "desc"]
        assert result == {"data": [], "total_count": 45, "has_more": True, "page": 2, "items_per_page": 20}

    @pytest.mark.asyncio
    async def test_every_filter_is_passed_through(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get_multi = AsyncMock(return_value={"data": [], "total_count": 0})
            await read_tasks(
                current_user=current_user_dict,
                db=mock_db,
                page=1,
                items_per_page=20,
                status="open",
                urgency="high",
                source="email",
                due_from=date(2026, 10, 1),
                due_to=date(2026, 10, 31),
            )

        kwargs = mock_crud.get_multi.call_args.kwargs
        assert kwargs["status"] == "open"
        assert kwargs["urgency"] == "high"
        assert kwargs["source"] == "email"
        assert kwargs["due_date__gte"] == date(2026, 10, 1)
        assert kwargs["due_date__lte"] == date(2026, 10, 31)

    @pytest.mark.asyncio
    async def test_unset_filters_are_not_sent(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get_multi = AsyncMock(return_value={"data": [], "total_count": 0})
            await read_tasks(current_user=current_user_dict, db=mock_db, page=1, items_per_page=20)

        kwargs = mock_crud.get_multi.call_args.kwargs
        for key in ("status", "urgency", "source", "due_date__gte", "due_date__lte"):
            assert key not in kwargs

    @pytest.mark.asyncio
    async def test_inverted_due_range_is_rejected(self, mock_db, current_user_dict):
        with pytest.raises(BadRequestException):
            await read_tasks(
                current_user=current_user_dict,
                db=mock_db,
                page=1,
                items_per_page=20,
                due_from=date(2026, 10, 31),
                due_to=date(2026, 10, 1),
            )


class TestReadTask:
    @pytest.mark.asyncio
    async def test_returns_owned_task(self, mock_db, current_user_dict):
        task = _owned_task(current_user_dict)
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=task)
            result = await read_task(task_id=task["id"], current_user=current_user_dict, db=mock_db)
        assert result == task
        _assert_lookup_hides_deleted(mock_crud)

    @pytest.mark.asyncio
    async def test_deleted_task_404(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)  # the is_deleted=False filter excludes it
            with pytest.raises(NotFoundException):
                await read_task(task_id=uuid7(), current_user=current_user_dict, db=mock_db)
        _assert_lookup_hides_deleted(mock_crud)

    @pytest.mark.asyncio
    async def test_other_users_task_403(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value={"user_id": uuid7()})
            with pytest.raises(ForbiddenException):
                await read_task(task_id=uuid7(), current_user=current_user_dict, db=mock_db)


class TestPatchTask:
    @pytest.mark.parametrize(
        ("field", "value", "flag"),
        [
            ("title", "Send the signed invoice", "title_manually_set"),
            ("description", "For the October work", "description_manually_set"),
            ("urgency", "high", "urgency_manually_set"),
            ("effort_level", "passive", "effort_level_manually_set"),
        ],
    )
    @pytest.mark.asyncio
    async def test_editing_a_sticky_field_sets_only_its_flag(self, mock_db, current_user_dict, field, value, flag):
        task = _owned_task(current_user_dict)
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(return_value=task)
            await patch_task(
                task_id=task["id"], body=TaskUpdate(**{field: value}), current_user=current_user_dict, db=mock_db
            )

        kwargs = mock_crud.update.call_args.kwargs
        assert kwargs["object"] == {field: value, flag: True}
        # without return_as_model, FastCRUD's update() returns None -> 500 on response validation
        assert kwargs["return_as_model"] is True and kwargs["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_due_date_edit_sets_no_flag(self, mock_db, current_user_dict):
        task = _owned_task(current_user_dict)
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(return_value=task)
            await patch_task(
                task_id=task["id"],
                body=TaskUpdate(due_date=date(2026, 10, 3)),
                current_user=current_user_dict,
                db=mock_db,
            )

        assert mock_crud.update.call_args.kwargs["object"] == {"due_date": date(2026, 10, 3)}

    @pytest.mark.asyncio
    async def test_clearing_description_is_a_manual_edit(self, mock_db, current_user_dict):
        task = _owned_task(current_user_dict)
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(return_value=task)
            await patch_task(
                task_id=task["id"], body=TaskUpdate(description=None), current_user=current_user_dict, db=mock_db
            )

        assert mock_crud.update.call_args.kwargs["object"] == {"description": None, "description_manually_set": True}

    @pytest.mark.parametrize("field", ["title", "urgency"])
    def test_explicit_null_rejected_for_required_fields(self, field):
        with pytest.raises(ValidationError):
            TaskUpdate(**{field: None})

    def test_status_not_accepted(self):
        with pytest.raises(ValidationError):
            TaskUpdate(status="done")  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_empty_body_writes_nothing(self, mock_db, current_user_dict):
        task = _owned_task(current_user_dict)
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock()
            result = await patch_task(task_id=task["id"], body=TaskUpdate(), current_user=current_user_dict, db=mock_db)

        assert result == task
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_notion_sync_enqueued(self, mock_db, current_user_dict):
        task = _owned_task(current_user_dict)
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(return_value=task)
            mock_queue.pool.enqueue_job = AsyncMock()
            await patch_task(
                task_id=task["id"], body=TaskUpdate(title="New"), current_user=current_user_dict, db=mock_db
            )

        mock_queue.pool.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_deleted_task_404(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            mock_crud.update = AsyncMock()
            with pytest.raises(NotFoundException):
                await patch_task(
                    task_id=uuid7(), body=TaskUpdate(title="New"), current_user=current_user_dict, db=mock_db
                )
        _assert_lookup_hides_deleted(mock_crud)
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_users_task_403(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value={"user_id": uuid7()})
            with pytest.raises(ForbiddenException):
                await patch_task(
                    task_id=uuid7(), body=TaskUpdate(title="New"), current_user=current_user_dict, db=mock_db
                )


class TestEraseTask:
    @pytest.mark.asyncio
    async def test_soft_deletes_without_touching_notion(self, mock_db, current_user_dict):
        task = _owned_task(current_user_dict)
        with (
            patch(f"{MODULE}.crud_tasks") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.delete = AsyncMock()
            mock_crud.db_delete = AsyncMock()
            mock_queue.pool.enqueue_job = AsyncMock()

            result = await erase_task(task_id=task["id"], current_user=current_user_dict, db=mock_db)

        assert result == {"message": "Task deleted."}
        mock_crud.delete.assert_called_once_with(db=mock_db, id=task["id"])
        mock_crud.db_delete.assert_not_called()
        mock_queue.pool.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_deleted_404(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            mock_crud.delete = AsyncMock()
            with pytest.raises(NotFoundException):
                await erase_task(task_id=uuid7(), current_user=current_user_dict, db=mock_db)
        _assert_lookup_hides_deleted(mock_crud)
        mock_crud.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_users_task_403(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value={"user_id": uuid7()})
            mock_crud.delete = AsyncMock()
            with pytest.raises(ForbiddenException):
                await erase_task(task_id=uuid7(), current_user=current_user_dict, db=mock_db)
        mock_crud.delete.assert_not_called()


class TestPatchTaskStatus:
    @pytest.mark.asyncio
    async def test_missing_task_raises_not_found(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundException):
                await patch_task_status(
                    task_id=uuid7(),
                    body=TaskStatusUpdate(status="done"),
                    current_user=current_user_dict,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_deleted_task_404(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.queue") as mock_queue:
            mock_crud.get = AsyncMock(return_value=None)
            mock_queue.pool.enqueue_job = AsyncMock()
            with pytest.raises(NotFoundException):
                await patch_task_status(
                    task_id=uuid7(),
                    body=TaskStatusUpdate(status="done"),
                    current_user=current_user_dict,
                    db=mock_db,
                )
        _assert_lookup_hides_deleted(mock_crud)
        mock_queue.pool.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_users_task_raises_forbidden(self, mock_db, current_user_dict):
        task = {"user_id": uuid7(), "status": "open"}  # not current_user's id
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get = AsyncMock(return_value=task)
            with pytest.raises(ForbiddenException):
                await patch_task_status(
                    task_id=uuid7(),
                    body=TaskStatusUpdate(status="done"),
                    current_user=current_user_dict,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_updates_status_and_enqueues_notion_sync_unconditionally(self, mock_db, current_user_dict):
        task_id = uuid7()
        task = {"user_id": current_user_dict["id"], "status": "open"}
        with (
            patch(f"{MODULE}.crud_tasks") as mock_crud,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(return_value={"status": "done"})
            mock_queue.pool.enqueue_job = AsyncMock()

            result = await patch_task_status(
                task_id=task_id, body=TaskStatusUpdate(status="done"), current_user=current_user_dict, db=mock_db
            )

        assert result["status"] == "done"
        assert mock_crud.update.call_args.kwargs["return_as_model"] is True
        mock_queue.pool.enqueue_job.assert_called_once_with("sync_status_to_notion", "task", str(task_id))


class TestTaskGoalLink:
    """Feature 1.9: the optional task -> goal link. The user may link a task to any of their
    own non-deleted goals; a link the user sets or clears is sticky (the AI never changes it)."""

    @pytest.mark.asyncio
    async def test_create_with_own_goal_is_a_sticky_link(self, mock_db, current_user_dict):
        goal_id = uuid7()
        with (
            patch(f"{MODULE}.crud_tasks") as mock_crud,
            patch(f"{MODULE}.crud_goals") as mock_goals,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_goals.get = AsyncMock(return_value={"id": goal_id})
            mock_crud.create = AsyncMock(return_value={"id": uuid7()})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_task(
                body=TaskCreate(title="Draft landing page", goal_id=goal_id), current_user=current_user_dict, db=mock_db
            )

        goal_filters = mock_goals.get.call_args.kwargs
        assert goal_filters["id"] == goal_id
        assert goal_filters["user_id"] == current_user_dict["id"] and goal_filters["is_deleted"] is False
        created = mock_crud.create.call_args.kwargs["object"]
        assert created.goal_id == goal_id and created.goal_id_manually_set is True

    @pytest.mark.asyncio
    async def test_create_without_goal_is_not_sticky_and_skips_the_check(self, mock_db, current_user_dict):
        with (
            patch(f"{MODULE}.crud_tasks") as mock_crud,
            patch(f"{MODULE}.crud_goals") as mock_goals,
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_goals.get = AsyncMock()
            mock_crud.create = AsyncMock(return_value={"id": uuid7()})
            mock_queue.pool.enqueue_job = AsyncMock()
            await write_task(body=TaskCreate(title="Draft landing page"), current_user=current_user_dict, db=mock_db)

        mock_goals.get.assert_not_called()
        created = mock_crud.create.call_args.kwargs["object"]
        assert created.goal_id is None and created.goal_id_manually_set is False

    @pytest.mark.asyncio
    async def test_missing_deleted_or_foreign_goal_is_rejected_on_create(self, mock_db, current_user_dict):
        """One lookup covers all three (filtered by user_id + is_deleted), and gives one
        message — never revealing whether someone else's goal exists."""
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.crud_goals") as mock_goals:
            mock_goals.get = AsyncMock(return_value=None)
            mock_crud.create = AsyncMock()
            with pytest.raises(BadRequestException, match="goal_id does not match any of your goals"):
                await write_task(
                    body=TaskCreate(title="x", goal_id=uuid7()), current_user=current_user_dict, db=mock_db
                )
        mock_crud.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_filters_by_goal(self, mock_db, current_user_dict):
        goal_id = uuid7()
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.get_multi = AsyncMock(return_value={"data": [], "total_count": 0})
            await read_tasks(current_user=current_user_dict, db=mock_db, page=1, items_per_page=20, goal_id=goal_id)
        kwargs = mock_crud.get_multi.call_args.kwargs
        assert kwargs["goal_id"] == goal_id and kwargs["user_id"] == current_user_dict["id"]

    @pytest.mark.asyncio
    async def test_patch_link_is_checked_and_sticky(self, mock_db, current_user_dict):
        task, goal_id = _owned_task(current_user_dict), uuid7()
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.crud_goals") as mock_goals:
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(return_value=task)
            mock_goals.get = AsyncMock(return_value={"id": goal_id})
            await patch_task(
                task_id=task["id"], body=TaskUpdate(goal_id=goal_id), current_user=current_user_dict, db=mock_db
            )
        assert mock_crud.update.call_args.kwargs["object"] == {"goal_id": goal_id, "goal_id_manually_set": True}

    @pytest.mark.asyncio
    async def test_patch_unlink_is_sticky_and_skips_the_check(self, mock_db, current_user_dict):
        task = _owned_task(current_user_dict)
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.crud_goals") as mock_goals:
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(return_value=task)
            mock_goals.get = AsyncMock()
            await patch_task(
                task_id=task["id"], body=TaskUpdate(goal_id=None), current_user=current_user_dict, db=mock_db
            )
        mock_goals.get.assert_not_called()
        assert mock_crud.update.call_args.kwargs["object"] == {"goal_id": None, "goal_id_manually_set": True}

    @pytest.mark.asyncio
    async def test_patch_to_other_users_goal_rejected(self, mock_db, current_user_dict):
        task = _owned_task(current_user_dict)
        with patch(f"{MODULE}.crud_tasks") as mock_crud, patch(f"{MODULE}.crud_goals") as mock_goals:
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock()
            mock_goals.get = AsyncMock(return_value=None)
            with pytest.raises(BadRequestException):
                await patch_task(
                    task_id=task["id"], body=TaskUpdate(goal_id=uuid7()), current_user=current_user_dict, db=mock_db
                )
        mock_crud.update.assert_not_called()
