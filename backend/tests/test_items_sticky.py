"""Unit tests for the sticky-override rules shared by tasks and goals (core/items/sticky.py)."""

import pytest

from src.app.core.items.sticky import (
    GOAL_STICKY_FLAGS,
    TASK_STICKY_FLAGS,
    drop_sticky_fields,
    manual_edit_flags,
)

NO_TASK_FLAGS = dict.fromkeys(TASK_STICKY_FLAGS.values(), False)
NO_GOAL_FLAGS = dict.fromkeys(GOAL_STICKY_FLAGS.values(), False)


class TestManualEditFlags:
    def test_flags_every_sticky_task_field_present(self):
        changes = {"title": "x", "description": None, "urgency": "high", "effort_level": "passive", "goal_id": None}
        assert manual_edit_flags(changes, TASK_STICKY_FLAGS) == dict.fromkeys(TASK_STICKY_FLAGS.values(), True)

    def test_non_sticky_fields_get_no_flag(self):
        assert manual_edit_flags({"due_date": None}, TASK_STICKY_FLAGS) == {}

    def test_goal_edit_flags_only_title_and_description(self):
        changes = {"title": "x", "description": "d", "horizon": "long_term", "target_date": None}
        assert manual_edit_flags(changes, GOAL_STICKY_FLAGS) == {
            "title_manually_set": True,
            "description_manually_set": True,
        }

    def test_goal_id_edit_including_unlink_is_sticky(self):
        assert manual_edit_flags({"goal_id": None}, TASK_STICKY_FLAGS) == {"goal_id_manually_set": True}


class TestDropStickyFields:
    @pytest.mark.parametrize(("field", "flag"), list(TASK_STICKY_FLAGS.items()))
    def test_each_task_flag_drops_only_its_own_field(self, field, flag):
        changes = {"title": "t", "description": "d", "urgency": "high", "effort_level": "passive", "goal_id": "g"}
        result = drop_sticky_fields(NO_TASK_FLAGS | {flag: True}, changes, TASK_STICKY_FLAGS)
        assert field not in result
        assert set(result) == set(changes) - {field}

    @pytest.mark.parametrize(("field", "flag"), list(GOAL_STICKY_FLAGS.items()))
    def test_each_goal_flag_drops_only_its_own_field(self, field, flag):
        changes = {"title": "t", "description": "d"}
        result = drop_sticky_fields(NO_GOAL_FLAGS | {flag: True}, changes, GOAL_STICKY_FLAGS)
        assert set(result) == set(changes) - {field}

    def test_no_flags_keeps_everything(self):
        changes = {"title": "t", "urgency": "low"}
        assert drop_sticky_fields(NO_TASK_FLAGS, changes, TASK_STICKY_FLAGS) == changes

    def test_non_sticky_fields_always_kept(self):
        all_flags = dict.fromkeys(TASK_STICKY_FLAGS.values(), True)
        assert drop_sticky_fields(all_flags, {"due_date": None, "title": "t"}, TASK_STICKY_FLAGS) == {"due_date": None}
