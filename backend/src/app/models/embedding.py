import uuid as uuid_pkg

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin

# Matches settings.EMBEDDING_DIMENSION (all-MiniLM-L6-v2). Hardcoded, not read from
# settings, because the column type is fixed at the DB level regardless of config — a
# model swap to a different dimension needs a new migration (and this literal) too.
EMBEDDING_DIMENSION = 384


class Embedding(Base, UUIDMixin, TimestampMixin):
    """One embedding per memory-extraction record (of its `summary` only) — a unique FK,
    not a shared table keyed some other way. Only conversation/email/notion summaries get
    embedded in practice; tasks/goals are a small relational list, no similarity search
    needed for them."""

    __tablename__ = "embeddings"

    memory_record_id: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_extraction_record.id", ondelete="CASCADE"), unique=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION))
