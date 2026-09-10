import uuid as uuid_pkg
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import TimestampSchema, UUIDSchema

IngestionSourceType = Literal["email", "calendar"]


class IngestionSyncBase(BaseModel):
    source_type: IngestionSourceType
    external_id: Annotated[str, Field(min_length=1, max_length=255)]
    content_fingerprint: Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]


class IngestionSync(TimestampSchema, IngestionSyncBase, UUIDSchema):
    """Full internal shape — never returned directly from a route (nothing routes this
    resource at all)."""

    user_id: uuid_pkg.UUID
    memory_record_id: uuid_pkg.UUID | None = None


class IngestionSyncRead(BaseModel):
    id: uuid_pkg.UUID
    source_type: IngestionSourceType
    external_id: str
    content_fingerprint: str
    memory_record_id: uuid_pkg.UUID | None = None
    created_at: datetime


class IngestionSyncCreate(IngestionSyncBase):
    """Public input shape — not routed. This resource is written only internally by
    `core/integrations/dedup.py`."""

    model_config = ConfigDict(extra="forbid")


class IngestionSyncCreateInternal(IngestionSyncBase):
    user_id: uuid_pkg.UUID
    memory_record_id: uuid_pkg.UUID | None = None


class IngestionSyncUpdate(BaseModel):
    """Defined for FastCRUD's generic signature — not routed. `dedup.py`'s own update
    call passes a plain dict, same convention as every other internal-only `.update()`
    call in this codebase (see `integrations_google.py`/`token_refresh.py`)."""

    model_config = ConfigDict(extra="forbid")

    content_fingerprint: str | None = None
    memory_record_id: uuid_pkg.UUID | None = None


class IngestionSyncUpdateInternal(IngestionSyncUpdate):
    updated_at: datetime


class IngestionSyncDelete(BaseModel):
    """Stub — hard-delete only, not routed this slice."""

    model_config = ConfigDict(extra="forbid")
