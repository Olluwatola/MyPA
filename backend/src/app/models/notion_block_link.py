from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class NotionBlockLink(Base, UUIDMixin, TimestampMixin):
    """Zero or more rows per block, one per actionable item it currently resolves to —
    a single block can produce more than one Task/Goal (see PRD §6.5), which is exactly
    why this is its own table rather than a column on Task/Goal. `item_id` is
    deliberately NOT a real foreign key — it points at either `tasks` or `goals`
    depending on `item_type`, which Postgres can't express as a single FK constraint; the
    application layer resolves it and is responsible for cleaning up a link row when its
    target is deleted. No `revoked_at` — unlinking hard-deletes the row."""

    __tablename__ = "notion_block_link"
    __table_args__ = (
        Index("ix_notion_block_link_user_block", "user_id", "notion_block_id"),
        UniqueConstraint("user_id", "item_type", "item_id", name="uq_notion_block_link_user_item"),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    notion_block_id: Mapped[str] = mapped_column(String(255))
    item_type: Mapped[str] = mapped_column(String(10))  # "task" | "goal"
    item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
