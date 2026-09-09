"""Local `sentence-transformers` embedding model — loaded once at app startup.

Local, not API-based: no API key/cost, CPU-friendly, deterministic. Loaded in a worker
thread (`anyio.to_thread.run_sync`) since both the model constructor and `.encode()` are
blocking, CPU-bound calls that would otherwise block the event loop.
"""

import anyio
from sentence_transformers import SentenceTransformer

from ..config import settings

_model: SentenceTransformer | None = None


async def init_embedding_model() -> None:
    global _model
    _model = await anyio.to_thread.run_sync(SentenceTransformer, settings.EMBEDDING_MODEL_NAME)

    # get_embedding_dimension() replaces the deprecated get_sentence_embedding_dimension()
    # as of sentence-transformers 5.x; fall back for older pins (>=3.0.0 per pyproject.toml).
    get_dimension = getattr(_model, "get_embedding_dimension", None) or _model.get_sentence_embedding_dimension
    dimension = get_dimension()
    if dimension != settings.EMBEDDING_DIMENSION:
        raise ValueError(
            f"Embedding model '{settings.EMBEDDING_MODEL_NAME}' produces {dimension}-dimension "
            f"vectors, but settings.EMBEDDING_DIMENSION is {settings.EMBEDDING_DIMENSION}. The "
            "embeddings table's Vector column is dimension-fixed at the DB level — a model swap "
            "needs a new migration too."
        )


async def embed_text(text: str) -> list[float]:
    if _model is None:
        raise RuntimeError("Embedding model not initialized — call init_embedding_model() at startup first.")

    embedding = await anyio.to_thread.run_sync(_model.encode, text)
    return embedding.tolist()  # type: ignore[no-any-return]
