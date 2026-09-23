import uuid as uuid_pkg
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..core.schemas import TimestampSchema, UUIDSchema


class NotionSharedPageBase(BaseModel):
    notion_page_id: str


class NotionSharedPage(TimestampSchema, NotionSharedPageBase, UUIDSchema):
    """Full internal shape — never returned directly from a route."""

    user_id: uuid_pkg.UUID
    granted_at: datetime
    revoked_at: datetime | None = None


class NotionSharedPageRead(BaseModel):
    id: uuid_pkg.UUID
    notion_page_id: str
    granted_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime


class NotionSharedPageCreateInternal(NotionSharedPageBase):
    """Created by the OAuth callback's initial page-search sync and by the reconciliation
    cron's ongoing diff — never posted directly by a client."""

    user_id: uuid_pkg.UUID
    granted_at: datetime


class NotionSharedPageUpdate(BaseModel):
    """Stub — defined for FastCRUD's generic signature; not routed this slice."""

    model_config = ConfigDict(extra="forbid")


class NotionSharedPageUpdateInternal(BaseModel):
    """Internal update fields — used by the reconciliation cron to grant/revoke."""

    granted_at: datetime | None = None
    revoked_at: datetime | None = None


class NotionSharedPageDelete(BaseModel):
    """Stub — revocation is a soft update (`revoked_at`), never a hard delete."""

    model_config = ConfigDict(extra="forbid")
