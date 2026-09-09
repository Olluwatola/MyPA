import uuid as uuid_pkg
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..core.schemas import TimestampSchema, UUIDSchema

IntegrationType = Literal["email", "calendar"]
IntegrationProvider = Literal["google", "outlook"]  # outlook unused this slice — see decisions-log.md


class IntegrationConnectionBase(BaseModel):
    type: IntegrationType
    provider: IntegrationProvider
    external_account_identifier: str | None = None


class IntegrationConnection(TimestampSchema, IntegrationConnectionBase, UUIDSchema):
    """Full internal shape — never returned directly from a route (carries encrypted
    token ciphertext)."""

    user_id: uuid_pkg.UUID
    access_token: str
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    scopes: str | None = None
    connected_at: datetime
    revoked_at: datetime | None = None
    watch_channel_id: str | None = None
    watch_resource_id: str | None = None
    watch_expires_at: datetime | None = None
    history_id: str | None = None
    channel_token: str | None = None


class IntegrationConnectionRead(BaseModel):
    """Public response shape — deliberately omits `access_token`/`refresh_token`/
    `channel_token` ciphertext. Exists for tests and a future Settings-page route; no
    GET/list route is wired this slice — out of scope, not silently added."""

    id: uuid_pkg.UUID
    type: IntegrationType
    provider: IntegrationProvider
    external_account_identifier: str | None = None
    connected_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime


class IntegrationConnectionCreate(IntegrationConnectionBase):
    """Public input shape — not routed this slice. A connection is only ever created via
    the OAuth callback (`IntegrationConnectionCreateInternal`), never posted directly by
    a client."""

    model_config = ConfigDict(extra="forbid")


class IntegrationConnectionCreateInternal(IntegrationConnectionBase):
    """Passed to CRUD by the OAuth callback's upsert."""

    user_id: uuid_pkg.UUID
    access_token: str
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    scopes: str | None = None
    connected_at: datetime


class IntegrationConnectionUpdate(BaseModel):
    """Defined for FastCRUD's generic signature — not routed this slice."""

    model_config = ConfigDict(extra="forbid")

    external_account_identifier: str | None = None
    revoked_at: datetime | None = None


class IntegrationConnectionUpdateInternal(BaseModel):
    """Internal update fields — used by the OAuth callback's upsert, the disconnect
    handler's soft revoke, and the watch-renewal job. Deliberately not a subclass of
    `IntegrationConnectionUpdate`: it touches fields (token ciphertext, watch state) a
    client-driven update should never be able to set."""

    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    scopes: str | None = None
    external_account_identifier: str | None = None
    connected_at: datetime | None = None
    revoked_at: datetime | None = None
    watch_channel_id: str | None = None
    watch_resource_id: str | None = None
    watch_expires_at: datetime | None = None
    history_id: str | None = None
    channel_token: str | None = None


class IntegrationConnectionDelete(BaseModel):
    """Stub — disconnect is a soft, local revoke via `IntegrationConnectionUpdateInternal`
    (see api/v1/integrations_google.py), never a hard delete. Not routed as an actual
    FastCRUD delete this slice."""

    model_config = ConfigDict(extra="forbid")
