"""The manual-create AI guess: fills a manually-created goal's empty `horizon` in the
background (core/goals/jobs.py).

Tier: `medium`, the same as the task guess (task_field_guess.py) — picking one of two
words for one short goal is a far smaller job than full memory extraction, and a wrong
guess is cheap (a visible value the user can change). Not `low`: that tier is Ollama,
which isn't installed (open item N-11).
"""

from datetime import date

from ...schemas.goal import GoalHorizonGuess
from . import service
from .provider import LlmMessage, LlmProviderResponseFormat
from .validation_retry import run_with_validation_retry

SYSTEM_PROMPT = (
    "You estimate whether ONE goal a user just typed into their personal assistant app is short_term "
    "(roughly within the next few months, or a concrete near deliverable) or long_term (ongoing, or a year "
    "or more away). If you genuinely can't tell, leave horizon out."
)

GOAL_HORIZON_GUESS_RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="guess_goal_horizon", schema_=GoalHorizonGuess.model_json_schema()
)


async def call_goal_horizon_guess_llm(
    title: str, description: str | None, target_date: date | None
) -> GoalHorizonGuess:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
    lines = [f"Title: {title}"]
    if description:
        lines.append(f"Description: {description}")
    if target_date:
        lines.append(f"Target date: {target_date.isoformat()}")
    return await run_with_validation_retry(
        llm_service=service.llm_service,
        tier="medium",
        messages=[LlmMessage(role="system", content=SYSTEM_PROMPT), LlmMessage(role="user", content="\n".join(lines))],
        response_format=GOAL_HORIZON_GUESS_RESPONSE_FORMAT,
        validate=GoalHorizonGuess.model_validate_json,
    )
