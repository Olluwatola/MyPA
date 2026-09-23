"""Receiver for Notion's webhook events — mirrors `webhooks_telegram.py`/
`webhooks_google_calendar.py`'s shape: a flat file (not a directory, despite the PRD
§8's directory wording — see decisions-log.md 2026-09-14), no `Depends(get_current_user)`
(identity is resolved inside the job, not here — this endpoint never touches the DB),
enqueue-and-204 only, never any Notion API/LLM work on the request path.

**Verification handshake:** Notion has no programmatic webhook-subscription API — setup
is dashboard-only. The FIRST delivery to a newly-configured endpoint is a bare, unsigned
`{"verification_token": "..."}` payload; a human copies that value into both the
dashboard and `settings.NOTION_WEBHOOK_VERIFICATION_TOKEN`. Every subsequent real
delivery carries `X-Notion-Signature: sha256=<hex>` — an HMAC-SHA256 of the raw body
keyed by that same verification token (Notion doesn't issue a separate webhook secret).

**Payload-shape caveat, stated not silently assumed:** the exact `data` shape for
`page.created` (and whether `data.updated_blocks` entries carry more than `{id, type}`
for `page.content_updated`) couldn't be confirmed from Notion's public docs at plan time.
This handler is deliberately shape-tolerant: `page.created` only uses `entity.id` and
lets the job do its own full fetch; `page.content_updated` treats `updated_blocks`
entries as candidate block ids only, never trusting any embedded freshness data. See the
Feature 1.7 planning notes' deferred live-verification step.
"""

import hashlib
import hmac
import json

from fastapi import APIRouter, Request, Response

from ...core.config import settings
from ...core.exceptions.http_exceptions import UnauthorizedException
from ...core.logger import logging
from ...core.utils import queue

router = APIRouter(prefix="/webhooks/notion", tags=["webhooks"])
logger = logging.getLogger(__name__)

INVALID_SIGNATURE_MESSAGE = "Invalid webhook signature."


@router.post("", status_code=204)
async def notion_webhook(request: Request) -> Response:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except ValueError:
        return Response(status_code=204)

    if "verification_token" in payload:
        # One-time bootstrap: a human copies this into settings and the Notion dashboard
        # (see this module's docstring). Never processed as a real event.
        logger.warning(f"Notion webhook verification token received: {payload['verification_token']}")
        return Response(status_code=200)

    signature = request.headers.get("X-Notion-Signature")
    expected = "sha256=" + hmac.new(
        settings.NOTION_WEBHOOK_VERIFICATION_TOKEN.get_secret_value().encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise UnauthorizedException(INVALID_SIGNATURE_MESSAGE)

    event_type = payload.get("type")
    page_id = payload.get("entity", {}).get("id")
    if not page_id:
        return Response(status_code=204)

    if event_type == "page.created":
        await queue.pool.enqueue_job(  # type: ignore[union-attr]
            "run_notion_initial_extraction", page_id, _job_id=f"notion-created-{page_id}"
        )
    elif event_type == "page.content_updated":
        block_ids = [block["id"] for block in payload.get("data", {}).get("updated_blocks", []) if "id" in block]
        await queue.pool.enqueue_job(  # type: ignore[union-attr]
            "process_notion_content_updated",
            page_id,
            block_ids,
            _job_id=f"notion-updated-{page_id}-{payload.get('id')}",
        )

    return Response(status_code=204)
