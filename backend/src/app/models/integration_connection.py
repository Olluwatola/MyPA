import uuid as uuid_pkg
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class IntegrationConnection(Base, UUIDMixin, TimestampMixin):
    """One row per (user, type, provider) — email and calendar are always two separate
    rows even when Google issues one combined token pair for both (see
    `api/v1/integrations_google.py`). The unique constraint below is plain, not
    partial-on-`revoked_at IS NULL` (the opposite choice from
    `ix_users_oauth_identity`) — connect/callback must upsert, never insert a second row
    for the same user+type+provider, so that disconnecting one type can never leave two
    rows both claiming overlapping ingested history. See decisions-log.md."""

    __tablename__ = "integration_connection"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "provider", name="uq_integration_connection_user_type_provider"),
    )

    user_id: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(20))  # "email" | "calendar"
    provider: Mapped[str] = mapped_column(String(20))  # "google" | "outlook" (outlook unused this slice)
    access_token: Mapped[str] = mapped_column(Text)  # Fernet ciphertext
    connected_at: Mapped[datetime]

    # Maps an inbound Gmail Pub/Sub notification (payload carries only the mailbox
    # address, never a user_id) back to a connection row. Doubles as Calendar's
    # primary-calendar id.
    external_account_identifier: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True, default=None
    )

    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    token_expires_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    scopes: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)

    # Watch/subscription renewal state (both mechanisms expire — see jobs.py's
    # renew_watches_before_expiry).
    watch_channel_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)  # Calendar only
    watch_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)  # Calendar only
    watch_expires_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)  # both
    history_id: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)  # Gmail only
    # Calendar only, Fernet ciphertext
    channel_token: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
