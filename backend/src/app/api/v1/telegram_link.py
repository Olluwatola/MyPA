"""Linking-flow endpoints for the Telegram channel — the deep-link mint and unlink.
Inbound `/start <token>` handling lives in `webhooks_telegram.py` instead (see that
module's docstring for why it isn't a separate route).

`GET /link` uses ordinary same-origin Bearer auth (`Depends(get_current_user)`) — unlike
the OAuth-callback's refresh-cookie-recovery pattern (integrations_google.py), which only
exists because that route is a cross-site redirect with no Bearer header available; this
route has one.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import NotFoundException
from ...core.telegram.linking import build_telegram_deep_link, create_link_token
from ...crud.crud_telegram_link import crud_telegram_link
from ...schemas.telegram_link import TelegramLinkUrlRead, TelegramUnlinkRead
from ..dependencies import get_current_user

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/link", response_model=TelegramLinkUrlRead, status_code=200)
async def read_telegram_link_url(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> TelegramLinkUrlRead:
    token = await create_link_token(current_user["id"])
    return TelegramLinkUrlRead(deep_link_url=build_telegram_deep_link(token))


@router.delete("/link", response_model=TelegramUnlinkRead, status_code=200)
async def erase_telegram_link(
    current_user: Annotated[dict, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(async_get_db)]
) -> TelegramUnlinkRead:
    link = await crud_telegram_link.get(db=db, user_id=current_user["id"])
    if not link:
        raise NotFoundException("No linked Telegram account found.")

    await crud_telegram_link.db_delete(db=db, id=link["id"])
    return TelegramUnlinkRead(status="unlinked")
