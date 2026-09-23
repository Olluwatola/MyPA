from fastcrud import FastCRUD

from ..models.notion_block_sync import NotionBlockSync
from ..schemas.notion_block_sync import (
    NotionBlockSyncCreateInternal,
    NotionBlockSyncDelete,
    NotionBlockSyncRead,
    NotionBlockSyncUpdate,
    NotionBlockSyncUpdateInternal,
)

CRUDNotionBlockSync = FastCRUD[
    NotionBlockSync,
    NotionBlockSyncCreateInternal,
    NotionBlockSyncUpdate,
    NotionBlockSyncUpdateInternal,
    NotionBlockSyncDelete,
    NotionBlockSyncRead,
]
crud_notion_block_sync = CRUDNotionBlockSync(NotionBlockSync)
