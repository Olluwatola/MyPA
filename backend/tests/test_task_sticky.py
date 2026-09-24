"""Unit tests for the sticky-override rules (core/tasks/sticky.py)."""

import pytest

from src.app.core.tasks.sticky import (
    STICKY_FLAG_BY_FIELD,
    drop_sticky_fields,
    manual_edit_flags,
)

NO_FLAGS = dict.fromkeys(STICKY_FLAG_BY_FIELD.values(), False)


class TestManualEditFlags:
    def test_flags_every_sticky_field_present(self):
        changes = {"title": "x", "description": None, "urgency": "high", "effort_level": "passive"}
        assert manual_edit_flags(changes) == dict.fromkeys(STICKY_FLAG_BY_FIELD.values(), True)

    def test_non_sticky_fields_get_no_flag(self):
        assert manual_edit_flags({"due_date": None}) == {}


class TestDropStickyFields:
    @pytest.mark.parametrize(("field", "flag"), list(STICKY_FLAG_BY_FIELD.items()))
    def test_each_flag_drops_only_its_own_field(self, field, flag):
        changes = {"title": "t", "description": "d", "urgency": "high", "effort_level": "passive"}
        result = drop_sticky_fields(NO_FLAGS | {flag: True}, changes)
        assert field not in result
        assert set(result) == set(changes) - {field}

    def test_no_flags_keeps_everything(self):
        changes = {"title": "t", "urgency": "low"}
        assert drop_sticky_fields(NO_FLAGS, changes) == changes

    def test_non_sticky_fields_always_kept(self):
        all_flags = dict.fromkeys(STICKY_FLAG_BY_FIELD.values(), True)
        assert drop_sticky_fields(all_flags, {"due_date": None, "title": "t"}) == {"due_date": None}
