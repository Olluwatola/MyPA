import uuid as uuid_pkg

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class IngestionSync(Base, UUIDMixin, TimestampMixin):
    """Per-item ingestion dedup — one row per (user, source item) ever successfully
    extracted. Shared across every ingestion code path (Gmail notification processing,
    Calendar webhook processing, onboarding bulk ingestion) so whichever path processes
    an item first, the others recognize it as already-synced. `content_fingerprint` is a
    plain sha256 hex digest, not SimHash — Gmail/Calendar content is one deterministic
    parsed string per fetch, no "typo vs. real edit" fuzzy-similarity case exists the way
    it does for Notion's free-text block editing (see decisions-log.md)."""

    __tablename__ = "ingestion_sync"
    __table_args__ = (
        UniqueConstraint("user_id", "source_type", "external_id", name="uq_ingestion_sync_user_source_external"),
    )

    user_id: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(20))  # "email" | "calendar"
    external_id: Mapped[str] = mapped_column(String(255))  # Gmail message id / Calendar event id
    content_fingerprint: Mapped[str] = mapped_column(String(64))  # sha256 hex digest

    memory_record_id: Mapped[uuid_pkg.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_extraction_record.id", ondelete="SET NULL"), nullable=True, default=None
    )
