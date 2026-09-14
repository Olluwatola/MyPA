from fastcrud import FastCRUD

from ..models.telegram_link import TelegramLink
from ..schemas.telegram_link import (
    TelegramLinkCreateInternal,
    TelegramLinkDelete,
    TelegramLinkRead,
    TelegramLinkUpdate,
    TelegramLinkUpdateInternal,
)

CRUDTelegramLink = FastCRUD[
    TelegramLink,
    TelegramLinkCreateInternal,
    TelegramLinkUpdate,
    TelegramLinkUpdateInternal,
    TelegramLinkDelete,
    TelegramLinkRead,
]
crud_telegram_link = CRUDTelegramLink(TelegramLink)
