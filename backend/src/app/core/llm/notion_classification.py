"""Edit-path classification — one LLM call PER CHANGED BLOCK, a deliberate override of
PRD §6.5 stage 4's own batching (confirmed 2026-09-23, see decisions-log.md): each call's
output covers exactly one block's outcome, at the cost of re-sending full-page context
once per changed block instead of once per page-edit event.

Does NOT reuse `core/llm/extraction.py::run_memory_extraction_pipeline`/
`call_extraction_llm` — Notion classification needs whole-page context, a three-way
outcome, multi-item resolution per block, and an anchored re-classification mode none of
that single-item interface supports. Still follows the exact same single-shot
structured-output template as `onboarding_synthesis.py` (module-level system prompt +
`*_RESPONSE_FORMAT` + `run_with_validation_retry`) — every LLM call in this feature stays
single-shot, never an agentic tool-calling loop (confirmed 2026-09-23).

Tier `"high"` — matches `extraction.py`'s own choice, since this call drives real
Task/Goal creation.
"""

import json
from typing import Any

from ...schemas.notion_classification import NotionAnchoredClassificationResult, NotionFreshClassificationResult
from ..goals.context import format_goals_for_prompt
from ..notion.client import NotionBlock
from . import service
from .provider import LlmMessage, LlmProviderResponseFormat
from .validation_retry import run_with_validation_retry

# Shared with notion_initial_extraction.py — the same linking rule everywhere the AI
# creates a Notion task (core/goals/context.py::resolve_goal_link decides what's kept).
GOAL_LINK_INSTRUCTIONS = (
    "For a TASK only, if one of the user's listed open goals is clearly what it serves, set goal_ref "
    "to that goal's number and goal_link_confidence honestly; otherwise leave both empty, and never "
    "refer to a goal that isn't listed. For a goal, due_date means its target date."
)

FRESH_SYSTEM_PROMPT = (
    "You classify a single block of user-written Notion content for a personal assistant app. "
    "You are given the block's own text plus the full text of the page it lives on, for context "
    "only — extraction is scoped to the target block alone, never to other blocks on the page. "
    "Decide one of three outcomes: 'not_actionable' (not a task/goal at all), 'actionable' (the "
    "block describes one or more concrete tasks or short/long-term goals — a single block can "
    "resolve to more than one item, e.g. 'finish the deck and email the client'), or "
    "'insufficient_context' (the block reads as actionable but can't be attributed to any "
    "specific project/goal even with the full page as context). For each actionable item, infer "
    "urgency and effort_level for tasks, and score confidence honestly — reserve high confidence "
    "(>= 0.7) for unambiguous commitments. " + GOAL_LINK_INSTRUCTIONS
)

ANCHORED_SYSTEM_PROMPT = (
    "You are re-evaluating a single Notion block that has already been extracted into one or more "
    "tracked items (shown to you below with their current title/description). The block's content "
    "has changed since it was last classified. For EACH existing item shown, decide whether the new "
    "text leaves it 'unchanged', 'updated' (and if so, provide the updated fields), or "
    "'no_longer_applies'. You must return exactly one entry per existing item shown — do not omit "
    "or add entries. Separately, decide whether the new text introduces any ADDITIONAL item beyond "
    "what's already linked, and whether — despite the edit — the block's meaning is now unclear "
    "enough to need clarification (insufficient_context=true). Use the full page text only as "
    "background context, never as new blocks to classify. For ADDITIONAL items only: " + GOAL_LINK_INSTRUCTIONS
)

FRESH_RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="classify_notion_block", schema_=NotionFreshClassificationResult.model_json_schema()
)
ANCHORED_RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="reclassify_notion_block", schema_=NotionAnchoredClassificationResult.model_json_schema()
)


def _block_prompt(full_page_text: str, target_block: NotionBlock) -> str:
    return (
        f"Full page text (context only):\n{full_page_text}\n\n"
        f"Target block (id={target_block.id}, type={target_block.type}):\n{target_block.plain_text}"
    )


def open_goals_prompt(open_goals: list[dict[str, Any]]) -> str:
    """The numbered open-goal block appended to a Notion prompt, or "" when there are none."""
    return f"\n\nThe user's open goals:\n{format_goals_for_prompt(open_goals)}" if open_goals else ""


async def classify_fresh_block(
    full_page_text: str, target_block: NotionBlock, open_goals: list[dict[str, Any]]
) -> NotionFreshClassificationResult:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
    return await run_with_validation_retry(
        llm_service=service.llm_service,
        tier="high",
        messages=[
            LlmMessage(role="system", content=FRESH_SYSTEM_PROMPT),
            LlmMessage(
                role="user", content=_block_prompt(full_page_text, target_block) + open_goals_prompt(open_goals)
            ),
        ],
        response_format=FRESH_RESPONSE_FORMAT,
        validate=NotionFreshClassificationResult.model_validate_json,
    )


async def reclassify_anchored_block(
    full_page_text: str,
    target_block: NotionBlock,
    existing_items: list[dict[str, Any]],
    open_goals: list[dict[str, Any]],
) -> NotionAnchoredClassificationResult:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
    existing_items_text = json.dumps(existing_items, default=str)
    content = (
        f"{_block_prompt(full_page_text, target_block)}\n\n"
        f"Currently-linked items for this block:\n{existing_items_text}"
        f"{open_goals_prompt(open_goals)}"
    )
    return await run_with_validation_retry(
        llm_service=service.llm_service,
        tier="high",
        messages=[
            LlmMessage(role="system", content=ANCHORED_SYSTEM_PROMPT),
            LlmMessage(role="user", content=content),
        ],
        response_format=ANCHORED_RESPONSE_FORMAT,
        validate=NotionAnchoredClassificationResult.model_validate_json,
    )
