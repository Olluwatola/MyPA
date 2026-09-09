from fastcrud import FastCRUD

from ..models.integration_connection import IntegrationConnection
from ..schemas.integration_connection import (
    IntegrationConnectionCreateInternal,
    IntegrationConnectionDelete,
    IntegrationConnectionRead,
    IntegrationConnectionUpdate,
    IntegrationConnectionUpdateInternal,
)

CRUDIntegrationConnection = FastCRUD[
    IntegrationConnection,
    IntegrationConnectionCreateInternal,
    IntegrationConnectionUpdate,
    IntegrationConnectionUpdateInternal,
    IntegrationConnectionDelete,
    IntegrationConnectionRead,
]
crud_integration_connections = CRUDIntegrationConnection(IntegrationConnection)
