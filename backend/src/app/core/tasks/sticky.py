"""Sticky-override rules (PRD §6.9, decisions-log.md 2026-09-24): once a user sets one of
these four fields by hand, no automated path — Notion re-classification, dedup
fill-blanks, the manual-create AI guess job — may change it again. One flag per field, so
fixing a title typo doesn't also freeze the description. There is no reset in 1.8."""

from typing import Any

STICKY_FLAG_BY_FIELD: dict[str, str] = {
    "title": "title_manually_set",
    "description": "description_manually_set",
    "urgency": "urgency_manually_set",
    "effort_level": "effort_level_manually_set",
}


def manual_edit_flags(changes: dict[str, Any]) -> dict[str, bool]:
    """Every sticky field present in a user edit gets its flag set — even when the value
    is unchanged or explicitly cleared (`null`), since both are an explicit user choice."""
    return {flag: True for field, flag in STICKY_FLAG_BY_FIELD.items() if field in changes}


def drop_sticky_fields(task: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """`changes` without any field whose sticky flag is already set on `task`."""
    return {
        field: value
        for field, value in changes.items()
        if not (field in STICKY_FLAG_BY_FIELD and task[STICKY_FLAG_BY_FIELD[field]])
    }
