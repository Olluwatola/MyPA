from fastcrud import FastCRUD

from ..models.ingestion_sync import IngestionSync
from ..schemas.ingestion_sync import (
    IngestionSyncCreateInternal,
    IngestionSyncDelete,
    IngestionSyncRead,
    IngestionSyncUpdate,
    IngestionSyncUpdateInternal,
)

CRUDIngestionSync = FastCRUD[
    IngestionSync, IngestionSyncCreateInternal, IngestionSyncUpdate, IngestionSyncUpdateInternal,
    IngestionSyncDelete, IngestionSyncRead,
]
crud_ingestion_sync = CRUDIngestionSync(IngestionSync)
