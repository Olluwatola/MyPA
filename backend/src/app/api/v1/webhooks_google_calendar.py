"""Receiver for Calendar's `events.watch()` push notifications.

**Validation mechanism:** Calendar channels don't cryptographically sign requests like
Telegram/Notion do. The one mechanism available is `channel_token` — an opaque secret
*we* generate at watch-registration time (stored encrypted on the connection row) that
Google echoes back verbatim as `X-Goog-Channel-Token`. Validation: look up the connection
by `X-Goog-Channel-Id`, decrypt the stored token, `hmac.compare_digest()` against the
header; an unknown channel-id or a mismatched token both come back as a generic "invalid
webhook channel" failure — the response never confirms whether a given channel-id exists.

The initial `X-Goog-Resource-State: sync` handshake is ack'd with 204 and does no
processing. Otherwise: enqueue `process_calendar_webhook` and return 204 immediately — no
Google API calls or LLM work on the request path.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.crypto import decrypt_token
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import NotFoundException, UnauthorizedException
from ...core.utils import queue
from ...crud.crud_integration_connections import crud_integration_connections

router = APIRouter(prefix="/webhooks/google", tags=["webhooks"])

INVALID_CHANNEL_MESSAGE = "Invalid webhook channel."


@router.post("/calendar", status_code=204)
async def google_calendar_webhook(
    db: Annotated[AsyncSession, Depends(async_get_db)],
    x_goog_channel_id: Annotated[str | None, Header(alias="X-Goog-Channel-Id")] = None,
    x_goog_channel_token: Annotated[str | None, Header(alias="X-Goog-Channel-Token")] = None,
    x_goog_resource_state: Annotated[str | None, Header(alias="X-Goog-Resource-State")] = None,
) -> Response:
    if not x_goog_channel_id:
        raise NotFoundException(INVALID_CHANNEL_MESSAGE)

    connection = await crud_integration_connections.get(
        db=db, watch_channel_id=x_goog_channel_id, type="calendar", provider="google"
    )
    if not connection or not connection["channel_token"]:
        raise NotFoundException(INVALID_CHANNEL_MESSAGE)

    expected_token = decrypt_token(connection["channel_token"])
    if not x_goog_channel_token or not hmac.compare_digest(x_goog_channel_token, expected_token):
        raise UnauthorizedException(INVALID_CHANNEL_MESSAGE)

    if x_goog_resource_state == "sync":
        return Response(status_code=204)

    await queue.pool.enqueue_job("process_calendar_webhook", str(connection["id"]))  # type: ignore[union-attr]
    return Response(status_code=204)
