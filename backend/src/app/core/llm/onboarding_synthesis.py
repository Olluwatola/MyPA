"""The onboarding goal-synthesis LLM call — a separate synthesis pass over the
just-created summaries from one onboarding ingestion run, not a reuse of the existing
per-item extraction pipeline's `goals` JSONB field. Per-item extraction is processed
blind to every other item, so it structurally cannot produce the cross-item
pattern-spotting ("recurring," "themes") the PRD asks for here (see decisions-log.md).

Tier: `medium`, not `high` — this is a lighter synthesis pass over already-summarized
text (each summary is itself the output of a `high`-tier extraction call), and unlike
extraction, nothing this call produces is auto-created (every suggestion stays an
unchecked checklist item until a human explicitly checks it).

Known, deferred risk: the prompt concatenates every summary from the run with no
truncation/pagination — an unusually large 14-day backlog could push the call over the
provider's context window. No PRD/decisions-log guidance exists on this yet.
"""

from ...schemas.goal import GoalSynthesisResult
from . import service
from .provider import LlmMessage, LlmProviderResponseFormat
from .validation_retry import run_with_validation_retry

SYSTEM_PROMPT = (
    "You are reviewing a batch of short summaries distilled from a user's recent starred/"
    "important emails and upcoming calendar events, gathered during onboarding. Look across "
    "all of them for cross-item patterns — recurring email threads, recent calendar themes, "
    "commitments implied by more than one item — and propose 3 to 5 candidate goals a personal "
    "assistant app could help the user track. Each candidate needs a short title, an optional "
    "one-sentence description, and a horizon (short_term or long_term) if reasonably clear; "
    "leave horizon out if it isn't. Do not invent goals unrelated to the provided summaries."
)

SYNTHESIS_RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="synthesize_onboarding_goals", schema_=GoalSynthesisResult.model_json_schema()
)


async def call_goal_synthesis_llm(summaries: list[tuple[str, str]]) -> GoalSynthesisResult:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
    content = "\n".join(f"[{source}] {summary}" for source, summary in summaries)
    return await run_with_validation_retry(
        llm_service=service.llm_service,
        tier="medium",
        messages=[LlmMessage(role="system", content=SYSTEM_PROMPT), LlmMessage(role="user", content=content)],
        response_format=SYNTHESIS_RESPONSE_FORMAT,
        validate=GoalSynthesisResult.model_validate_json,
    )
