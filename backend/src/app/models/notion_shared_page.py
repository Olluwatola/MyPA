from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class NotionSharedPage(Base, UUIDMixin, TimestampMixin):
    """One row per Notion page the user has shared with the integration — our own
    tracked list, not a live call to Notion's API on every check (see decisions-log.md,
    2026-09-06). `revoked_at` is latest grant/revoke state, not a full history — a page
    that's re-shared after being unshared just clears it back to `None`.

    `DateTime(timezone=True)` is explicit on both datetime columns — see
    `models/notion_connection.py`'s docstring for why a bare `Mapped[datetime]` breaks
    against this codebase's always-tz-aware `datetime.now(UTC)` writes."""

    __tablename__ = "notion_shared_page"
    __table_args__ = (UniqueConstraint("user_id", "notion_page_id", name="uq_notion_shared_page_user_page"),)

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notion_page_id: Mapped[str] = mapped_column(String(255), index=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
