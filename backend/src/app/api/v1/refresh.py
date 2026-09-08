import uuid as uuid_pkg

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import UnauthorizedException
from ...core.security import TokenType, blacklist_token, create_access_token, create_refresh_token, verify_token
from ...schemas.token import Token
from .login import _set_refresh_cookie

router = APIRouter(tags=["auth"])


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    request: Request, response: Response, db: AsyncSession = Depends(async_get_db)
) -> dict[str, str]:
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise UnauthorizedException("Refresh token missing.")

    payload = await verify_token(refresh_token, TokenType.REFRESH, db)
    if not payload:
        raise UnauthorizedException("Invalid refresh token.")

    # Rotate: blacklist the old refresh token, issue a fresh pair.
    await blacklist_token(payload, db)

    user_id = uuid_pkg.UUID(payload.sub)
    new_access_token, _ = await create_access_token(user_id=user_id)
    new_refresh_token, _ = await create_refresh_token(user_id=user_id)

    _set_refresh_cookie(response, new_refresh_token)

    return {"access_token": new_access_token, "token_type": "bearer"}
