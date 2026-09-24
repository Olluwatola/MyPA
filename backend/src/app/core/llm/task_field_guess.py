"""The manual-create AI guess: fills a manually-created task's empty `urgency` and/or
`effort_level` in the background (core/tasks/jobs.py).

Tier: `medium`, not `high` — guessing two fields from one short task is a far smaller
job than full memory extraction, and a wrong guess is cheap (a visible default the user
can change). Not `low`: that tier is Ollama, which isn't installed (open item N-11).
"""

from datetime import date

from ...schemas.task import TaskFieldGuess
from . import service
from .provider import LlmMessage, LlmProviderResponseFormat
from .validation_retry import run_with_validation_retry

SYSTEM_PROMPT = (
    "You estimate missing fields for ONE task a user just typed into their personal assistant app. "
    "Only fill the fields you are asked for. Urgency is low, medium or high: use high only for explicit "
    "time pressure or importance ('urgent', 'ASAP', 'today', a close due date), low for clearly "
    "optional/someday items, otherwise medium. Effort level is deep_focus (needs sustained concentration), "
    "light_focus (routine, needs some attention) or passive (can be done absent-mindedly). If you genuinely "
    "can't tell, leave the field out."
)

TASK_FIELD_GUESS_RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="guess_task_fields", schema_=TaskFieldGuess.model_json_schema()
)


async def call_task_field_guess_llm(
    title: str, description: str | None, due_date: date | None, fields: list[str]
) -> TaskFieldGuess:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
    lines = [f"Title: {title}"]
    if description:
        lines.append(f"Description: {description}")
    if due_date:
        lines.append(f"Due date: {due_date.isoformat()}")
    lines.append(f"Fields to fill: {', '.join(fields)}")
    return await run_with_validation_retry(
        llm_service=service.llm_service,
        tier="medium",
        messages=[LlmMessage(role="system", content=SYSTEM_PROMPT), LlmMessage(role="user", content="\n".join(lines))],
        response_format=TASK_FIELD_GUESS_RESPONSE_FORMAT,
        validate=TaskFieldGuess.model_validate_json,
    )
