import uuid as uuid_pkg
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import NotFoundException, UnauthorizedException
from ...core.oauth.google import build_google_authorize_url, exchange_code_for_tokens, fetch_google_userinfo
from ...core.security import create_refresh_token
from ...crud.crud_users import crud_users
from ...schemas.user import UserCreateInternal, UserRead
from .login import _set_refresh_cookie

router = APIRouter(prefix="/auth/google", tags=["auth"])

STATE_COOKIE = "oauth_state"


@router.get("/login")
async def google_login() -> RedirectResponse:
    state = str(uuid_pkg.uuid4())
    redirect = RedirectResponse(url=build_google_authorize_url(state))
    redirect.set_cookie(key=STATE_COOKIE, value=state, httponly=True, secure=True, samesite="lax", max_age=600)
    return redirect


@router.get("/callback")
async def google_callback(
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    db: Annotated[AsyncSession, Depends(async_get_db)],
    oauth_state: Annotated[str | None, Cookie(alias=STATE_COOKIE)] = None,
) -> RedirectResponse:
    if not oauth_state or oauth_state != state:
        raise UnauthorizedException("Invalid OAuth state.")

    google_tokens = await exchange_code_for_tokens(code)
    userinfo = await fetch_google_userinfo(google_tokens["access_token"])

    if not userinfo.email_verified:
        raise UnauthorizedException("Google account email is not verified.")

    db_user = await crud_users.get(db=db, oauth_provider="google", oauth_sub=userinfo.sub)

    if not db_user:
        # Auto-link: a verified Google email matching an existing password account
        # attaches to that same row rather than being rejected as a conflict.
        db_user = await crud_users.get(db=db, email=userinfo.email)
        if db_user:
            await crud_users.update(
                db=db, object={"oauth_provider": "google", "oauth_sub": userinfo.sub}, id=db_user["id"]
            )
            db_user = await crud_users.get(db=db, id=db_user["id"])
            if not db_user:
                raise NotFoundException("User vanished between linking and reload.")
        else:
            user_internal = UserCreateInternal(
                first_name=userinfo.given_name or userinfo.email.split("@")[0],
                last_name=userinfo.family_name,
                email=userinfo.email,
                hashed_password=None,
                oauth_provider="google",
                oauth_sub=userinfo.sub,
            )
            db_user = await crud_users.create(db=db, object=user_internal, schema_to_select=UserRead)

    # Only a refresh cookie is set here — a bare redirect can't hand a SPA an access
    # token in the response body. The frontend calls POST /api/v1/refresh immediately
    # after landing to obtain one.
    user_id = uuid_pkg.UUID(str(db_user["id"]))
    refresh_token, _ = await create_refresh_token(user_id=user_id)

    redirect = RedirectResponse(url=settings.FRONTEND_OAUTH_CALLBACK_URL)
    _set_refresh_cookie(redirect, refresh_token)
    redirect.delete_cookie(key=STATE_COOKIE)
    return redirect
