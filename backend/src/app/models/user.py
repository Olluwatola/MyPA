from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """A tenant. No SoftDeleteMixin — nothing deletes a user in Phase 1 (deliberate
    divergence from the template's default `User`, which soft-deletes; logged in
    decisions-log.md)."""

    __tablename__ = "users"

    first_name: Mapped[str] = mapped_column(String(30))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    # Nullable: not everyone has a second name (common in several cultures), and
    # Google's own OAuth data doesn't always carry a family_name for every account.
    last_name: Mapped[str | None] = mapped_column(String(30), nullable=True, default=None)

    # Nullable: an OAuth-only user (Google sign-in, never set a password) has no hash.
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    # Google link stored directly on users (nullable) rather than a separate table —
    # Phase 1 has exactly one OAuth provider.
    oauth_provider: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    oauth_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)

    # Needed later for the 7am-local morning briefing.
    timezone: Mapped[str] = mapped_column(String(50), server_default="UTC", default="UTC")

    # Standard get_current_superuser dependency needs this even with no admin feature yet.
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    # Onboarding state — stored directly on `users`, matching the exact precedent already
    # set for briefing settings (see erd.md's "Resolved" and decisions-log.md). First
    # onboarding-state fields on `users` at all.
    onboarding_status: Mapped[str] = mapped_column(
        String(20), default="not_started"
    )  # not_started | pending | ready | completed
    onboarding_suggested_goals: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
