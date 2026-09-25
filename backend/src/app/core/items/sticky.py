"""Sticky-override rules for tasks and goals (PRD §6.9, decisions-log.md 2026-09-24): once a
user sets one of these fields by hand, no automated path — Notion re-classification, dedup
fill-blanks, the manual-create AI guess jobs — may change it again. One flag per field, so
fixing a title typo doesn't also freeze the description. There is no reset.

`goal_id` is sticky on tasks: a link the user set (or cleared) is never changed by the AI.
"""

from typing import Any

TASK_STICKY_FLAGS: dict[str, str] = {
    "title": "title_manually_set",
    "description": "description_manually_set",
    "urgency": "urgency_manually_set",
    "effort_level": "effort_level_manually_set",
    "goal_id": "goal_id_manually_set",
}

GOAL_STICKY_FLAGS: dict[str, str] = {
    "title": "title_manually_set",
    "description": "description_manually_set",
}


def manual_edit_flags(changes: dict[str, Any], sticky_flags: dict[str, str]) -> dict[str, bool]:
    """Every sticky field present in a user edit gets its flag set — even when the value
    is unchanged or explicitly cleared (`null`), since both are an explicit user choice."""
    return {flag: True for field, flag in sticky_flags.items() if field in changes}


def drop_sticky_fields(item: dict[str, Any], changes: dict[str, Any], sticky_flags: dict[str, str]) -> dict[str, Any]:
    """`changes` without any field whose sticky flag is already set on `item`."""
    return {
        field: value for field, value in changes.items() if not (field in sticky_flags and item[sticky_flags[field]])
    }
