import uuid as uuid_pkg
from typing import Literal

from pydantic import BaseModel

from ..core.schemas import TimestampSchema, UUIDSchema

NotionLinkItemType = Literal["task", "goal"]


class NotionBlockLinkBase(BaseModel):
    notion_block_id: str
    item_type: NotionLinkItemType
    item_id: uuid_pkg.UUID


class NotionBlockLinkCreate(NotionBlockLinkBase):
    """Created internally by the persistence helper — never posted directly by a client.
    Reused for FastCRUD's Update/UpdateInternal/Delete generic slots too (same trick as
    `EmbeddingCreate`): nothing in this slice ever updates a link row in place, and
    unlinking uses `db_delete` directly rather than a FastCRUD generic delete call."""

    user_id: uuid_pkg.UUID


class NotionBlockLinkRead(TimestampSchema, NotionBlockLinkBase, UUIDSchema):
    pass
