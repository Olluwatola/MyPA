"""Semantic search over past memory-extraction summaries.

Raw SQLAlchemy `select()`, not FastCRUD's generic query builder — FastCRUD's generic
query builder doesn't support ordering by a vector-distance expression.
"""

import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.embedding import Embedding
from ...models.memory_extraction_record import MemoryExtractionRecord
from ..config import settings
from .embedding_model import embed_text


async def search_similar_memories(
    db: AsyncSession, user_id: uuid_pkg.UUID, query_text: str, top_k: int | None = None
) -> list[MemoryExtractionRecord]:
    top_k = top_k or settings.MEMORY_RETRIEVAL_TOP_K
    query_vector = await embed_text(query_text)

    stmt = (
        select(MemoryExtractionRecord)
        .join(Embedding, Embedding.memory_record_id == MemoryExtractionRecord.id)
        .where(MemoryExtractionRecord.user_id == user_id)
        .order_by(Embedding.embedding.cosine_distance(query_vector))
        .limit(top_k)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
