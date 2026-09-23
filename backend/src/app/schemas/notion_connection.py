import uuid as uuid_pkg
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..core.schemas import TimestampSchema, UUIDSchema


class NotionConnectionBase(BaseModel):
    workspace_name: str | None = None


class NotionConnection(TimestampSchema, NotionConnectionBase, UUIDSchema):
    """Full internal shape — never returned directly from a route (carries encrypted
    token ciphertext)."""

    user_id: uuid_pkg.UUID
    access_token: str
    connected_at: datetime
    revoked_at: datetime | None = None


class NotionConnectionRead(BaseModel):
    """Public response shape — deliberately omits `access_token` ciphertext."""

    id: uuid_pkg.UUID
    workspace_name: str | None = None
    connected_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime


class NotionConnectionCreateInternal(NotionConnectionBase):
    """Created only from the OAuth callback — never posted directly by a client."""

    user_id: uuid_pkg.UUID
    access_token: str
    connected_at: datetime


class NotionConnectionUpdate(BaseModel):
    """Stub — defined for FastCRUD's generic signature; not routed this slice."""

    model_config = ConfigDict(extra="forbid")


class NotionConnectionUpdateInternal(BaseModel):
    """Internal update fields — used by the OAuth callback's upsert and the disconnect
    handler's soft revoke."""

    access_token: str | None = None
    workspace_name: str | None = None
    connected_at: datetime | None = None
    revoked_at: datetime | None = None


class NotionConnectionDelete(BaseModel):
    """Stub — disconnect is a soft, local revoke (see api/v1/integrations_notion.py),
    never a hard delete."""

    model_config = ConfigDict(extra="forbid")
