import uuid as uuid_pkg
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import UnauthorizedException
from ...core.security import authenticate_user, create_access_token, create_refresh_token
from ...schemas.token import Token

router = APIRouter(tags=["auth"])


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/api/v1",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


@router.post("/login", response_model=Token)
async def login_for_access_token(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    user = await authenticate_user(email=form_data.username, password=form_data.password, db=db)
    if not user:
        raise UnauthorizedException("Wrong email or password.")

    user_id = uuid_pkg.UUID(str(user["id"]))
    access_token, _ = await create_access_token(user_id=user_id)
    refresh_token, _ = await create_refresh_token(user_id=user_id)

    _set_refresh_cookie(response, refresh_token)

    return {"access_token": access_token, "token_type": "bearer"}
