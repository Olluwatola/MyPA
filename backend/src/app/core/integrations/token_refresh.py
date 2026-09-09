"""Shared access-token freshness check — used by every Gmail/Calendar job before any
Gmail/Calendar API call."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_integration_connections import crud_integration_connections
from ..crypto import decrypt_token, encrypt_token
from ..oauth.google import refresh_google_access_token

SAFETY_MARGIN = timedelta(minutes=2)


async def get_valid_access_token(db: AsyncSession, connection: dict[str, Any]) -> str:
    """Returns a decrypted, valid access token for `connection` — refreshing (and
    re-persisting the newly-encrypted token) first if it's within `SAFETY_MARGIN` of
    `token_expires_at`, or that field is unset."""
    expires_at = connection.get("token_expires_at")
    needs_refresh = expires_at is None or expires_at <= datetime.now(UTC) + SAFETY_MARGIN

    if not needs_refresh:
        return decrypt_token(connection["access_token"])

    if not connection.get("refresh_token"):
        # No refresh token on file — nothing to refresh with. Hand back the
        # possibly-stale token and let the caller's own API call surface the real 401.
        return decrypt_token(connection["access_token"])

    refresh_token = decrypt_token(connection["refresh_token"])
    tokens = await refresh_google_access_token(refresh_token)

    new_access_token: str = tokens["access_token"]
    expires_in = tokens.get("expires_in")
    new_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in) if expires_in else None

    # A plain dict, not IntegrationConnectionUpdateInternal — FastCRUD's own .update()
    # is typed against IntegrationConnectionUpdate (the public-shape schema kept only to
    # satisfy FastCRUD's generic signature, see schemas/integration_connection.py); every
    # internal-only update in this codebase goes through a dict for that reason (same
    # convention as api/v1/oauth_google.py's crud_users.update() call).
    await crud_integration_connections.update(
        db=db,
        object={"access_token": encrypt_token(new_access_token), "token_expires_at": new_expires_at},
        id=connection["id"],
    )

    return new_access_token
