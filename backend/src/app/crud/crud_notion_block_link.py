from fastcrud import FastCRUD

from ..models.notion_block_link import NotionBlockLink
from ..schemas.notion_block_link import NotionBlockLinkCreate, NotionBlockLinkRead

# Append/delete-only table — NotionBlockLinkCreate reused for Update/UpdateInternal/
# Delete generic slots too (same trick as crud_embeddings.py); nothing ever updates a
# link row in place, and unlinking uses db_delete directly.
CRUDNotionBlockLink = FastCRUD[
    NotionBlockLink,
    NotionBlockLinkCreate,
    NotionBlockLinkCreate,
    NotionBlockLinkCreate,
    NotionBlockLinkCreate,
    NotionBlockLinkRead,
]
crud_notion_block_link = CRUDNotionBlockLink(NotionBlockLink)
