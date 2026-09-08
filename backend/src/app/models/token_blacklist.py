from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class TokenBlacklist(Base, UUIDMixin, TimestampMixin):
    """Stores only the token's `jti` claim, never the raw JWT."""

    __tablename__ = "token_blacklist"

    jti: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    token_type: Mapped[str] = mapped_column(String(10))  # "access" | "refresh"
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
