"""Connect/callback/disconnect for the Notion OAuth integration — mirrors
`api/v1/integrations_google.py`'s shape closely, with the differences Notion's own
model forces:

- Notion issues one access token per connecting user (no combined multi-type grant like
  Google's Gmail+Calendar), so there's exactly one `NotionConnection` row per user, not
  two — no sibling-revocation dance needed on disconnect.
- No refresh token / expiry — Notion access tokens don't expire, so there's no
  `core/notion/token_refresh.py` equivalent; the stored token is used as-is until revoked.
- The callback is still a plain browser redirect (only `code`/`state` query params +
  cookies, no `Authorization` header) — the user is recovered from the existing httponly
  `refresh_token` cookie, exactly like Google's integrations callback.
"""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.crypto import encrypt_token
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import NotFoundException, UnauthorizedException
from ...core.logger import logging
from ...core.notion.client import search_accessible_pages
from ...core.notion.oauth import build_notion_authorize_url, exchange_code_for_tokens
from ...core.security import TokenType, verify_token
from ...crud.crud_notion_connection import crud_notion_connection
from ...crud.crud_notion_shared_page import crud_notion_shared_page
from ...schemas.notion_connection import NotionConnectionCreateInternal, NotionConnectionRead
from ...schemas.notion_shared_page import NotionSharedPageCreateInternal
from ..dependencies import get_current_user

router = APIRouter(prefix="/integrations/notion", tags=["integrations"])
logger = logging.getLogger(__name__)

STATE_COOKIE = "notion_integrations_oauth_state"


@router.get("/connect")
async def connect_notion_integration(current_user: Annotated[dict, Depends(get_current_user)]) -> RedirectResponse:
    state = str(uuid_pkg.uuid4())
    authorize_url = build_notion_authorize_url(state, redirect_uri=settings.NOTION_INTEGRATIONS_REDIRECT_URI)
    redirect = RedirectResponse(url=authorize_url)
    redirect.set_cookie(key=STATE_COOKIE, value=state, httponly=True, secure=True, samesite="lax", max_age=600)
    return redirect


@router.get("/callback")
async def notion_integrations_callback(
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    db: Annotated[AsyncSession, Depends(async_get_db)],
    oauth_state: Annotated[str | None, Cookie(alias=STATE_COOKIE)] = None,
    refresh_token_cookie: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> RedirectResponse:
    if not oauth_state or oauth_state != state:
        raise UnauthorizedException("Invalid OAuth state.")

    if not refresh_token_cookie:
        raise UnauthorizedException("Not authenticated.")
    payload = await verify_token(refresh_token_cookie, TokenType.REFRESH, db)
    if not payload:
        raise UnauthorizedException("Not authenticated.")
    user_id = uuid_pkg.UUID(payload.sub)

    notion_tokens = await exchange_code_for_tokens(code, redirect_uri=settings.NOTION_INTEGRATIONS_REDIRECT_URI)
    notion_access_token: str = notion_tokens["access_token"]
    workspace_name: str | None = notion_tokens.get("workspace_name")

    encrypted_access_token = encrypt_token(notion_access_token)
    connected_at = datetime.now(UTC)

    await _upsert_connection(
        db=db,
        user_id=user_id,
        access_token=encrypted_access_token,
        workspace_name=workspace_name,
        connected_at=connected_at,
    )

    # Populate the initial shared-page grant list right away (the page picker just ran
    # as part of this OAuth flow) rather than waiting for the reconciliation cron's next
    # tick — see core/notion/resolution.py for the ongoing diff.
    await _sync_shared_pages(db, user_id, notion_access_token)

    redirect = RedirectResponse(url=settings.FRONTEND_NOTION_INTEGRATIONS_CALLBACK_URL)
    redirect.delete_cookie(key=STATE_COOKIE)
    return redirect


async def _upsert_connection(
    db: AsyncSession,
    user_id: uuid_pkg.UUID,
    access_token: str,
    workspace_name: str | None,
    connected_at: datetime,
) -> None:
    existing = await crud_notion_connection.get(db=db, user_id=user_id)
    if existing:
        # A plain dict, not NotionConnectionUpdateInternal — every internal-only update
        # in this codebase goes through a dict (same convention as
        # integrations_google.py's _upsert_connection).
        await crud_notion_connection.update(
            db=db,
            object={
                "access_token": access_token,
                "workspace_name": workspace_name,
                "connected_at": connected_at,
                "revoked_at": None,
            },
            id=existing["id"],
        )
    else:
        await crud_notion_connection.create(
            db=db,
            object=NotionConnectionCreateInternal(
                user_id=user_id, access_token=access_token, workspace_name=workspace_name, connected_at=connected_at
            ),
            schema_to_select=NotionConnectionRead,
        )


async def _sync_shared_pages(db: AsyncSession, user_id: uuid_pkg.UUID, access_token: str) -> None:
    granted_at = datetime.now(UTC)
    pages = await search_accessible_pages(access_token)
    for page in pages:
        existing = await crud_notion_shared_page.get(db=db, user_id=user_id, notion_page_id=page["id"])
        if existing:
            if existing["revoked_at"] is not None:
                await crud_notion_shared_page.update(
                    db=db, object={"revoked_at": None, "granted_at": granted_at}, id=existing["id"]
                )
        else:
            await crud_notion_shared_page.create(
                db=db,
                object=NotionSharedPageCreateInternal(
                    user_id=user_id, notion_page_id=page["id"], granted_at=granted_at
                ),
            )


@router.delete("")
async def disconnect_notion_integration(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    connection = await crud_notion_connection.get(db=db, user_id=current_user["id"])
    if not connection or connection["revoked_at"] is not None:
        raise NotFoundException("No connected Notion integration found.")

    await crud_notion_connection.update(db=db, object={"revoked_at": datetime.now(UTC)}, id=connection["id"])
    return {"status": "disconnected"}
