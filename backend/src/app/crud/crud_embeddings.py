from fastcrud import FastCRUD

from ..models.embedding import Embedding
from ..schemas.embedding import EmbeddingCreate, EmbeddingRead

# Append-only table — EmbeddingCreate reused for Update/UpdateInternal/Delete generic
# slots too (same trick as crud_token_blacklist.py); nothing ever updates or deletes an
# embedding.
CRUDEmbedding = FastCRUD[Embedding, EmbeddingCreate, EmbeddingCreate, EmbeddingCreate, EmbeddingCreate, EmbeddingRead]
crud_embeddings = CRUDEmbedding(Embedding)
