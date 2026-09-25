"""Initial-extraction chunk classification (`page.created` path) — one LLM call PER
CHUNK, run in parallel by the orchestrator (`core/notion/initial_extraction.py`). A
third, distinct mechanism from both the edit path (one call per changed block) and the
PRD's own original "one call for the whole page" suggestion — confirmed 2026-09-23,
modeled on `vitlycare/monolith-be`'s CEIS pipeline's chunking/parallel-extraction
architecture (chunking/dedup shape only, not its PII/contact-matching machinery, which
solves an unrelated problem).

No three-way outcome / insufficient-context here (that's scoped to the edit path only,
a deliberate line, not an oversight) — a chunk just returns zero or more confidence-
scored items, tagged with which block they came from.
"""

from typing import Any

from ...schemas.notion_classification import NotionChunkExtractionResult
from ..notion.client import NotionBlock
from . import service
from .notion_classification import GOAL_LINK_INSTRUCTIONS, open_goals_prompt
from .provider import LlmMessage, LlmProviderResponseFormat
from .validation_retry import run_with_validation_retry

SYSTEM_PROMPT = (
    "You extract actionable tasks and goals from a newly-created Notion page for a personal "
    "assistant app. You are given the full page's text as background context, plus an in-scope "
    "list of specific blocks to extract from — extract ONLY from the in-scope blocks, using the "
    "full page purely to interpret them (e.g. knowing which project a line belongs to). A plain "
    "bulleted list item or even a sentence in a paragraph can be actionable; formatting is not a "
    "requirement. Tag every returned item with the exact block id (source_block_id) it came from, "
    "from the in-scope list. A single block can produce more than one item. Score confidence "
    "honestly — reserve high confidence (>= 0.7) for unambiguous commitments. " + GOAL_LINK_INSTRUCTIONS
)

CHUNK_RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="extract_notion_chunk", schema_=NotionChunkExtractionResult.model_json_schema()
)


def _format_in_scope_blocks(chunk_blocks: list[NotionBlock]) -> str:
    return "\n".join(f"[block: {block.id}] {block.type}: {block.plain_text}" for block in chunk_blocks)


async def extract_chunk(
    full_page_text: str, chunk_blocks: list[NotionBlock], open_goals: list[dict[str, Any]]
) -> NotionChunkExtractionResult:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
    content = (
        f"Full page text (background context only):\n{full_page_text}\n\n"
        f"In-scope blocks to extract from:\n{_format_in_scope_blocks(chunk_blocks)}"
        f"{open_goals_prompt(open_goals)}"
    )
    return await run_with_validation_retry(
        llm_service=service.llm_service,
        tier="high",
        messages=[LlmMessage(role="system", content=SYSTEM_PROMPT), LlmMessage(role="user", content=content)],
        response_format=CHUNK_RESPONSE_FORMAT,
        validate=NotionChunkExtractionResult.model_validate_json,
    )
