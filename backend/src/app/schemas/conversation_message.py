import uuid as uuid_pkg
from typing import Literal

from pydantic import BaseModel

from ..core.schemas import TimestampSchema, UUIDSchema


class ConversationMessageBase(BaseModel):
    user_id: uuid_pkg.UUID
    role: Literal["user", "assistant"]
    channel: Literal["in_app", "telegram"]
    content: str


class ConversationMessageCreate(ConversationMessageBase):
    """Append-only — created internally by the webhook/jobs, never posted directly by a
    client. Reused for FastCRUD's Update/UpdateInternal/Delete generic slots too (same
    trick as `MemoryExtractionRecordCreate`/`EmbeddingCreate`): rows are only ever
    created or hard-deleted in bulk by the retention cron, never individually updated."""


class ConversationMessageRead(TimestampSchema, ConversationMessageBase, UUIDSchema):
    pass
