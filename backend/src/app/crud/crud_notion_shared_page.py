from fastcrud import FastCRUD

from ..models.notion_shared_page import NotionSharedPage
from ..schemas.notion_shared_page import (
    NotionSharedPageCreateInternal,
    NotionSharedPageDelete,
    NotionSharedPageRead,
    NotionSharedPageUpdate,
    NotionSharedPageUpdateInternal,
)

CRUDNotionSharedPage = FastCRUD[
    NotionSharedPage,
    NotionSharedPageCreateInternal,
    NotionSharedPageUpdate,
    NotionSharedPageUpdateInternal,
    NotionSharedPageDelete,
    NotionSharedPageRead,
]
crud_notion_shared_page = CRUDNotionSharedPage(NotionSharedPage)
