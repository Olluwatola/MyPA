"""Connect/callback/disconnect for the combined Gmail + Calendar OAuth grant.

**Real issue found and resolved:** the callback route is a plain browser redirect (only
`code`/`state` query params + cookies — no `Authorization` header), so
`Depends(get_current_user)` cannot work there (it requires a Bearer token via
`oauth2_scheme`). Resolution: recover the user from the existing httponly `refresh_token`
cookie already set at login, via `verify_token(cookie_value, TokenType.REFRESH, db)` — the
one credential this route actually has available. `/connect` (the button click that
starts the flow) *does* have a real Bearer token and uses `Depends(get_current_user)`
normally.

**Combined-grant, with a real nuance:** Gmail + Calendar scopes are requested together in
one `/authorize` call (one consent screen, one code, one token pair) — `access_type=
"offline"` + `prompt="consent"` so Google actually issues a refresh_token (background
jobs need one to stay connected past the access token's lifetime). But the ERD models
email/calendar as **two separate** `integration_connection` rows, each storing its own
encrypted copy of the same underlying token pair. Consequence: per-type disconnect must
be a soft, local revoke only (`revoked_at` + stop that type's own watch) — it must not
call Google's `/revoke` unless the sibling row is *also* already revoked, since revoking
with Google invalidates the shared token and would silently kill the still-connected type
too.
"""

import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Cookie, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.crypto import decrypt_token, encrypt_token
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import NotFoundException, UnauthorizedException
from ...core.integrations.gmail import gmail_get_profile, gmail_stop_watch
from ...core.integrations.google_calendar import calendar_stop_watch
from ...core.integrations.onboarding import trigger_onboarding_run
from ...core.logger import logging
from ...core.oauth.google import build_google_authorize_url, exchange_code_for_tokens, revoke_google_token
from ...core.security import TokenType, verify_token
from ...crud.crud_integration_connections import crud_integration_connections
from ...schemas.integration_connection import (
    IntegrationConnectionCreateInternal,
    IntegrationConnectionRead,
    IntegrationType,
)
from ..dependencies import get_current_user

router = APIRouter(prefix="/integrations/google", tags=["integrations"])
logger = logging.getLogger(__name__)

STATE_COOKIE = "integrations_oauth_state"
INTEGRATION_TYPES: tuple[IntegrationType, ...] = ("email", "calendar")


@router.get("/connect")
async def connect_google_integrations(current_user: Annotated[dict, Depends(get_current_user)]) -> RedirectResponse:
    state = str(uuid_pkg.uuid4())
    redirect = RedirectResponse(
        url=build_google_authorize_url(
            state,
            scope=settings.GOOGLE_GMAIL_CALENDAR_SCOPES,
            access_type="offline",  # background jobs need a refresh_token, not just a session-lived grant
            prompt="consent",  # guarantees Google re-issues a refresh_token even on a repeat connect
            redirect_uri=settings.GOOGLE_INTEGRATIONS_REDIRECT_URI,
        )
    )
    redirect.set_cookie(key=STATE_COOKIE, value=state, httponly=True, secure=True, samesite="lax", max_age=600)
    return redirect


@router.get("/callback")
async def google_integrations_callback(
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

    google_tokens = await exchange_code_for_tokens(code, redirect_uri=settings.GOOGLE_INTEGRATIONS_REDIRECT_URI)
    google_access_token: str = google_tokens["access_token"]
    google_refresh_token: str | None = google_tokens.get("refresh_token")
    expires_in = google_tokens.get("expires_in")
    token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in) if expires_in else None
    scopes = google_tokens.get("scope")

    # One call to get the connected mailbox address — used as `external_account_identifier`
    # for both rows (Calendar's primary calendar id is the same address).
    profile = await gmail_get_profile(google_access_token)
    mailbox_address: str = profile["emailAddress"]

    encrypted_access_token = encrypt_token(google_access_token)
    encrypted_refresh_token = encrypt_token(google_refresh_token) if google_refresh_token else None
    connected_at = datetime.now(UTC)

    # Does not register the watch inline — the renewal cron job (jobs.py) picks up rows
    # with watch_expires_at IS NULL on its next run instead, keeping the slow third-party
    # call off the request path.
    for integration_type in INTEGRATION_TYPES:
        await _upsert_connection(
            db=db,
            user_id=user_id,
            integration_type=integration_type,
            access_token=encrypted_access_token,
            refresh_token=encrypted_refresh_token,
            token_expires_at=token_expires_at,
            scopes=scopes,
            external_account_identifier=mailbox_address,
            connected_at=connected_at,
        )

    # Both connection rows are upserted above — "both connected" is trivially true the
    # moment this callback succeeds (one combined scope grant). Enqueue the onboarding
    # ingestion pass directly, unconditionally.
    await trigger_onboarding_run(db, user_id)

    redirect = RedirectResponse(url=settings.FRONTEND_INTEGRATIONS_CALLBACK_URL)
    redirect.delete_cookie(key=STATE_COOKIE)
    return redirect


async def _upsert_connection(
    db: AsyncSession,
    user_id: uuid_pkg.UUID,
    integration_type: IntegrationType,
    access_token: str,
    refresh_token: str | None,
    token_expires_at: datetime | None,
    scopes: str | None,
    external_account_identifier: str,
    connected_at: datetime,
) -> None:
    """The unique constraint on `(user_id, type, provider)` is plain, not
    partial-on-`revoked_at IS NULL` — a second row must never be inserted for the same
    user+type+provider, so a prior (possibly revoked) row is always updated, never
    duplicated. `revoked_at=None` clears a prior disconnect on reconnect."""
    existing = await crud_integration_connections.get(db=db, user_id=user_id, type=integration_type, provider="google")
    if existing:
        # A plain dict, not IntegrationConnectionUpdateInternal — FastCRUD's own
        # .update() is typed against IntegrationConnectionUpdate (kept only to satisfy
        # FastCRUD's generic signature); every internal-only update in this codebase goes
        # through a dict for that reason (same convention as oauth_google.py's
        # crud_users.update() call).
        await crud_integration_connections.update(
            db=db,
            object={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_expires_at": token_expires_at,
                "scopes": scopes,
                "external_account_identifier": external_account_identifier,
                "connected_at": connected_at,
                "revoked_at": None,
            },
            id=existing["id"],
        )
    else:
        await crud_integration_connections.create(
            db=db,
            object=IntegrationConnectionCreateInternal(
                user_id=user_id,
                type=integration_type,
                provider="google",
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
                scopes=scopes,
                external_account_identifier=external_account_identifier,
                connected_at=connected_at,
            ),
            schema_to_select=IntegrationConnectionRead,
        )


@router.delete("/{integration_type}")
async def disconnect_google_integration(
    integration_type: Literal["email", "calendar"],
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    connection = await crud_integration_connections.get(
        db=db, user_id=current_user["id"], type=integration_type, provider="google"
    )
    if not connection or connection["revoked_at"] is not None:
        raise NotFoundException(f"No connected {integration_type} integration found.")

    await _stop_watch(integration_type, connection)

    await crud_integration_connections.update(
        db=db,
        object={"revoked_at": datetime.now(UTC)},
        id=connection["id"],
    )

    # The disconnect handler checks the sibling's revoked_at before ever calling
    # revoke_google_token — revoking with Google would silently kill the still-connected
    # sibling type too, since both rows share the same underlying token.
    sibling_type: IntegrationType = "calendar" if integration_type == "email" else "email"
    sibling = await crud_integration_connections.get(
        db=db, user_id=current_user["id"], type=sibling_type, provider="google"
    )
    sibling_already_revoked = sibling is None or sibling["revoked_at"] is not None
    if sibling_already_revoked:
        try:
            await revoke_google_token(decrypt_token(connection["access_token"]))
        except httpx.HTTPStatusError:
            # Already invalid/expired at Google's end — not fatal to a local disconnect.
            logger.warning("revoke_google_token failed during disconnect", exc_info=True)

    return {"status": "disconnected"}


async def _stop_watch(integration_type: Literal["email", "calendar"], connection: dict[str, Any]) -> None:
    try:
        if integration_type == "calendar" and connection["watch_channel_id"] and connection["watch_resource_id"]:
            access_token = decrypt_token(connection["access_token"])
            await calendar_stop_watch(access_token, connection["watch_channel_id"], connection["watch_resource_id"])
        elif integration_type == "email" and connection["watch_expires_at"]:
            access_token = decrypt_token(connection["access_token"])
            await gmail_stop_watch(access_token)
    except httpx.HTTPStatusError:
        # A watch that's already expired/stopped at Google's end isn't fatal to a local
        # disconnect — the renewal job will simply never see this (now-revoked) row again.
        logger.warning(f"stop_watch failed for {integration_type} during disconnect", exc_info=True)
