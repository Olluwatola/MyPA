from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class NotionBlockSync(Base, UUIDMixin, TimestampMixin):
    """Exactly one row per tracked block, always — change-detection watermark state
    (`last_edited_time`, `content_fingerprint`) is a property of the block itself, not of
    whatever item it currently resolves to (see PRD §6.5). `content_fingerprint` is a
    64-bit SimHash (see core/notion/simhash.py) stored as a signed BigInteger — a
    deliberately different type/algorithm from `ingestion_sync.content_fingerprint`'s
    exact sha256-hex `String`, since this needs fuzzy near-duplicate comparison, not exact
    match. `clarification_requested_at` avoids re-asking the same "insufficient context"
    question on every subsequent event while one is already outstanding.

    `DateTime(timezone=True)` is explicit on both datetime columns — see
    `models/notion_connection.py`'s docstring for why a bare `Mapped[datetime]` breaks
    against this codebase's always-tz-aware `datetime.now(UTC)` writes."""

    __tablename__ = "notion_block_sync"
    __table_args__ = (
        UniqueConstraint("user_id", "notion_block_id", name="uq_notion_block_sync_user_block"),
        Index("ix_notion_block_sync_user_page", "user_id", "notion_page_id"),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    notion_block_id: Mapped[str] = mapped_column(String(255))
    notion_page_id: Mapped[str] = mapped_column(String(255))
    last_edited_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_fingerprint: Mapped[int] = mapped_column(BigInteger)
    clarification_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
