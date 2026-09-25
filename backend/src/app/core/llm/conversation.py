"""Channel-agnostic ad-hoc-chat reply pipeline — sibling to extraction.py/
onboarding_synthesis.py/retrieval.py, deliberately not Telegram-specific so a future
in-app chat endpoint can reuse `generate_conversation_reply` unchanged.

Also owns the `conversation_message` retention cron — co-located here (not in
`core/telegram/`) since the table itself is channel-agnostic, not Telegram-specific.
"""

import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_conversation_messages import crud_conversation_messages
from ...schemas.conversation_message import ConversationMessageRead
from ..db.database import local_session
from ..goals.context import format_goals_for_chat, load_open_goals
from . import service
from .provider import LlmMessage
from .retrieval import search_similar_memories

CONVERSATION_HISTORY_LIMIT = 10
CONVERSATION_MESSAGE_RETENTION = timedelta(days=7)

SYSTEM_PROMPT = (
    "You are MyPA, a helpful personal assistant chatting with the user over a messaging "
    "channel. Reply conversationally and concisely, grounding your answer in the "
    "conversation history and any remembered context provided below. When the user asks what "
    "to focus on, weigh their open goals."
)


async def generate_conversation_reply(db: AsyncSession, user_id: uuid_pkg.UUID) -> str:
    """Reads the persisted last-N turns (already includes the just-stored current user
    turn as the most recent row — the caller stores that row BEFORE calling this) and
    generates the next reply. Never risks the current turn appearing twice in the prompt,
    since this function only ever reads what's already persisted."""
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."

    result = await crud_conversation_messages.get_multi(
        db=db,
        user_id=user_id,
        sort_columns="created_at",
        sort_orders="desc",
        limit=CONVERSATION_HISTORY_LIMIT,
        schema_to_select=ConversationMessageRead,
        return_total_count=False,
    )
    recent = list(reversed(result["data"]))  # type: ignore[arg-type]

    relevant = await search_similar_memories(db, user_id, recent[-1]["content"])

    messages = [LlmMessage(role="system", content=SYSTEM_PROMPT)]
    if relevant:
        memory_block = "\n".join(f"- {record.summary}" for record in relevant)
        messages.append(LlmMessage(role="system", content=f"Relevant remembered context:\n{memory_block}"))

    # Open goals only (PRD §5.9) — paused/dropped/done/deleted are left out by the loader.
    open_goals = await load_open_goals(db, user_id)
    if open_goals:
        messages.append(
            LlmMessage(
                role="system",
                content=(
                    "The user's open goals (use them when helping them prioritise):\n"
                    f"{format_goals_for_chat(open_goals)}"
                ),
            )
        )
    messages += [LlmMessage(role=row["role"], content=row["content"]) for row in recent]

    result_completion = await service.llm_service.complete(tier="medium", messages=messages)
    return result_completion.text


async def cleanup_expired_conversation_messages(ctx: dict[str, Any]) -> None:
    """Cron, daily. The 7-day window is a deliberate privacy-conscious middle ground —
    only the verbatim raw text expires; the summarized memory from extraction survives
    indefinitely regardless."""
    cutoff = datetime.now(UTC) - CONVERSATION_MESSAGE_RETENTION
    async with local_session() as db:
        await crud_conversation_messages.db_delete(db=db, allow_multiple=True, created_at__lt=cutoff)
