from fastcrud import FastCRUD

from ..models.notion_connection import NotionConnection
from ..schemas.notion_connection import (
    NotionConnectionCreateInternal,
    NotionConnectionDelete,
    NotionConnectionRead,
    NotionConnectionUpdate,
    NotionConnectionUpdateInternal,
)

CRUDNotionConnection = FastCRUD[
    NotionConnection,
    NotionConnectionCreateInternal,
    NotionConnectionUpdate,
    NotionConnectionUpdateInternal,
    NotionConnectionDelete,
    NotionConnectionRead,
]
crud_notion_connection = CRUDNotionConnection(NotionConnection)
