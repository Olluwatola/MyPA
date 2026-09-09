import uuid as uuid_pkg

from pydantic import BaseModel

from ..core.schemas import TimestampSchema, UUIDSchema


class EmbeddingBase(BaseModel):
    memory_record_id: uuid_pkg.UUID
    embedding: list[float]


class EmbeddingCreate(EmbeddingBase):
    """Created internally alongside a `MemoryExtractionRecord` — never posted directly.
    Reused for FastCRUD's Update/UpdateInternal/Delete generic slots too (same trick as
    `TokenBlacklistUpdate`): nothing in this slice ever updates or deletes an embedding."""


class EmbeddingRead(TimestampSchema, EmbeddingBase, UUIDSchema):
    pass
