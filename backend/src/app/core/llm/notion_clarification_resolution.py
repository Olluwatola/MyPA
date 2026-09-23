"""Light resolution pass over a user's free-text reply to a Notion "insufficient
context" clarifying question — tier `"medium"`, not `"high"`: this interprets a short
reply against a short list of candidate goals, a much lighter task than full-page
classification (same tier-choice reasoning as `onboarding_synthesis.py`). Single-shot
structured-output call, `run_with_validation_retry` template, same as every other LLM
call in this feature.
"""

import json
from typing import Any

from ...schemas.notion_classification import NotionClarificationResolution
from . import service
from .provider import LlmMessage, LlmProviderResponseFormat
from .validation_retry import run_with_validation_retry

SYSTEM_PROMPT = (
    "A user was asked which existing goal a piece of Notion content belongs to, or whether it's "
    "something new. You are given the original block's summary, a list of candidate existing goals "
    "(id + title), and the user's free-text reply. If the reply clearly picks one of the candidate "
    "goals (by name or close paraphrase), return its id as matched_existing_goal_id. Otherwise, if "
    "the reply describes a new task or goal, return it as new_item with your best-guess confidence. "
    "If the reply is itself ambiguous or doesn't resolve anything, return both fields as null."
)

RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="resolve_notion_clarification", schema_=NotionClarificationResolution.model_json_schema()
)


async def resolve_clarification_reply(
    reply_text: str, candidate_goals: list[dict[str, Any]], block_summary: str
) -> NotionClarificationResolution:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
    content = (
        f"Original block summary: {block_summary}\n"
        f"Candidate existing goals: {json.dumps(candidate_goals, default=str)}\n"
        f"User's reply: {reply_text}"
    )
    return await run_with_validation_retry(
        llm_service=service.llm_service,
        tier="medium",
        messages=[LlmMessage(role="system", content=SYSTEM_PROMPT), LlmMessage(role="user", content=content)],
        response_format=RESPONSE_FORMAT,
        validate=NotionClarificationResolution.model_validate_json,
    )
