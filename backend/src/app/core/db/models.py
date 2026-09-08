import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column
from uuid6 import uuid7


class UUIDMixin(MappedAsDataclass):
    """UUID primary key, named `id` (not `uuid`) so every model exposes the same
    ownership-check shape used across the app: `current_user["id"]`."""

    id: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, insert_default=uuid7, server_default=text("gen_random_uuid()"), init=False
    )


class TimestampMixin(MappedAsDataclass):
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=lambda: datetime.now(UTC),
        server_default=text("current_timestamp(0)"),
        init=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, onupdate=lambda: datetime.now(UTC), init=False
    )


class SoftDeleteMixin(MappedAsDataclass):
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, init=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, init=False)
