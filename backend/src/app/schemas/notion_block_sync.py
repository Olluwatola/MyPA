import uuid as uuid_pkg
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..core.schemas import TimestampSchema, UUIDSchema


class NotionBlockSyncBase(BaseModel):
    notion_block_id: str
    notion_page_id: str
    last_edited_time: datetime
    content_fingerprint: int


class NotionBlockSync(TimestampSchema, NotionBlockSyncBase, UUIDSchema):
    """Full internal shape — never returned directly from a route."""

    user_id: uuid_pkg.UUID
    clarification_requested_at: datetime | None = None


class NotionBlockSyncRead(BaseModel):
    id: uuid_pkg.UUID
    notion_block_id: str
    notion_page_id: str
    last_edited_time: datetime
    content_fingerprint: int
    clarification_requested_at: datetime | None = None
    created_at: datetime


class NotionBlockSyncCreateInternal(NotionBlockSyncBase):
    """Created internally by the 3-stage edit gate / initial-extraction watermark
    write — never posted directly by a client."""

    user_id: uuid_pkg.UUID


class NotionBlockSyncUpdate(BaseModel):
    """Stub — defined for FastCRUD's generic signature; not routed this slice."""

    model_config = ConfigDict(extra="forbid")


class NotionBlockSyncUpdateInternal(BaseModel):
    """Internal update fields — watermark refresh (stage 2 no-op path) and clarification
    flag set/clear."""

    last_edited_time: datetime | None = None
    content_fingerprint: int | None = None
    clarification_requested_at: datetime | None = None


class NotionBlockSyncDelete(BaseModel):
    """Stub — a block-identity change (tagging conversion) hard-deletes the old row
    directly via `db_delete`, never a FastCRUD generic delete call."""

    model_config = ConfigDict(extra="forbid")
