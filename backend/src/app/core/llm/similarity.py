"""In-memory embedding comparison — the genuine gap this codebase didn't have before
Feature 1.7. `core/llm/retrieval.py`'s `.cosine_distance()` is a pgvector SQLAlchemy
comparator that only works as part of a query executed against Postgres; comparing two
arbitrary in-memory embedding vectors (e.g. two candidate facts extracted from
overlapping Notion chunks, before either is ever persisted) needs its own plain-Python
implementation. `numpy` is already a transitive dependency via `sentence-transformers`/
torch — no new package.
"""

import numpy as np


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vector_a = np.asarray(a, dtype=np.float64)
    vector_b = np.asarray(b, dtype=np.float64)

    norm_a = np.linalg.norm(vector_a)
    norm_b = np.linalg.norm(vector_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return float(np.dot(vector_a, vector_b) / (norm_a * norm_b))
