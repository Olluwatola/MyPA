from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.security import blacklist_token, decode_token_ignoring_expiry, oauth2_scheme

router = APIRouter(tags=["auth"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_user(
    response: Response,
    access_token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
    refresh_token: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> None:
    access_payload = decode_token_ignoring_expiry(access_token)
    if access_payload:
        await blacklist_token(access_payload, db)

    if refresh_token:
        refresh_payload = decode_token_ignoring_expiry(refresh_token)
        if refresh_payload:
            await blacklist_token(refresh_payload, db)

    response.delete_cookie(key="refresh_token", path="/api/v1")
