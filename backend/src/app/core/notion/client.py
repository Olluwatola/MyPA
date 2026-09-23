"""Notion API client — plain `httpx`, no vendor SDK (matches this project's Google/
Telegram precedent). Every non-trivial shape below was verified against Notion's public
API reference (developers.notion.com, API version 2022-06-28) rather than assumed — see
the Feature 1.7 planning notes for what could and couldn't be confirmed.

Rate limits (~180 req/min per connection/workspace, 429 + `Retry-After`) are handled via
`execute_with_retry`'s existing 429-retry — the same helper Gmail/Calendar/Telegram
already use, reused here rather than reinvented.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from ..logger import logging
from ..utils.http_retry import execute_with_retry

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
RETRYABLE_STATUS_CODES = frozenset({429})


@dataclass
class NotionBlock:
    id: str
    type: str
    plain_text: str
    last_edited_time: datetime
    has_children: bool
    parent: dict[str, Any]
    raw: dict[str, Any]


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def extract_plain_text(raw_block: dict[str, Any]) -> str:
    """Concatenates `rich_text[].plain_text` for whichever type key the block has.
    Blocks with no rich text of their own (dividers, images, etc.) resolve to ""."""
    block_type = raw_block.get("type")
    if not block_type:
        return ""
    type_payload = raw_block.get(block_type) or {}
    rich_text = type_payload.get("rich_text") or []
    return "".join(segment.get("plain_text", "") for segment in rich_text)


def _to_notion_block(raw: dict[str, Any]) -> NotionBlock:
    return NotionBlock(
        id=raw["id"],
        type=raw["type"],
        plain_text=extract_plain_text(raw),
        last_edited_time=datetime.fromisoformat(raw["last_edited_time"].replace("Z", "+00:00")),
        has_children=raw.get("has_children", False),
        parent=raw.get("parent", {}),
        raw=raw,
    )


async def list_block_children(access_token: str, block_id: str, start_cursor: str | None = None) -> dict[str, Any]:
    """`GET /v1/blocks/{block_id}/children` — one page of results.
    Response shape: `{"results": [...], "has_more": bool, "next_cursor": str | None}`."""
    params: dict[str, Any] = {"page_size": 100}
    if start_cursor:
        params["start_cursor"] = start_cursor

    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.get(
                f"{NOTION_API_BASE}/blocks/{block_id}/children",
                headers=_headers(access_token),
                params=params,
                timeout=30.0,
            )

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


async def fetch_all_blocks_recursive(access_token: str, page_id: str) -> list[NotionBlock]:
    """Flattens an entire page's block tree into document order: paginates
    `list_block_children` for `page_id`, and for every block with `has_children=True`,
    recurses into it depth-first, inserting its children immediately after it — so
    surrounding-block context (used everywhere in classification prompts) reads the way a
    human would read the page top to bottom."""
    blocks: list[NotionBlock] = []
    start_cursor: str | None = None
    while True:
        page = await list_block_children(access_token, page_id, start_cursor)
        for raw in page["results"]:
            block = _to_notion_block(raw)
            blocks.append(block)
            if block.has_children:
                blocks.extend(await fetch_all_blocks_recursive(access_token, block.id))
        if not page.get("has_more"):
            break
        start_cursor = page.get("next_cursor")
    return blocks


async def get_block(access_token: str, block_id: str) -> NotionBlock:
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.get(
                f"{NOTION_API_BASE}/blocks/{block_id}", headers=_headers(access_token), timeout=30.0
            )

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()
    return _to_notion_block(response.json())


async def update_block_checkbox(access_token: str, block_id: str, checked: bool) -> NotionBlock:
    """`PATCH /v1/blocks/{block_id}` with `{"to_do": {"checked": bool}}` — only valid for
    a block whose `type` is already `to_do`; callers are responsible for that (the
    tagging conversion in `core/notion/tagging.py` guarantees it)."""
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.patch(
                f"{NOTION_API_BASE}/blocks/{block_id}",
                headers=_headers(access_token),
                json={"to_do": {"checked": checked}},
                timeout=30.0,
            )

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()
    return _to_notion_block(response.json())


async def append_block(
    access_token: str, parent_id: str, after_block_id: str, block_payload: dict[str, Any]
) -> NotionBlock:
    """`PATCH /v1/blocks/{parent_id}/children` — `parent_id` is the PARENT (page or
    block) whose children list is being appended to, not `after_block_id` itself; Notion
    cannot change a block's type in place, so converting a plain list item to a `to_do`
    (see `core/notion/tagging.py`) inserts a brand-new block via this call and then
    archives the original with `delete_block`. `after` places the new block immediately
    following `after_block_id` among its siblings; the response's `results[0]` is the
    newly-created block."""
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.patch(
                f"{NOTION_API_BASE}/blocks/{parent_id}/children",
                headers=_headers(access_token),
                json={"children": [block_payload], "after": after_block_id},
                timeout=30.0,
            )

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()
    results: list[dict[str, Any]] = response.json()["results"]
    return _to_notion_block(results[0])


async def delete_block(access_token: str, block_id: str) -> None:
    """`DELETE /v1/blocks/{block_id}` — Notion's "delete" is an archive (`archived:
    true`), not a hard removal; that's sufficient for the tagging-conversion use case
    (the original block's content already lives in the newly-appended replacement)."""
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.delete(
                f"{NOTION_API_BASE}/blocks/{block_id}", headers=_headers(access_token), timeout=30.0
            )

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()


async def search_accessible_pages(access_token: str) -> list[dict[str, Any]]:
    """`POST /v1/search` filtered to pages — used at OAuth-connect time and by the
    reconciliation cron to enumerate every page currently shared with the integration
    (Notion has no "list my webhook subscriptions" or "list shares" endpoint; search is
    the closest available primitive)."""
    pages: list[dict[str, Any]] = []
    start_cursor: str | None = None
    async with httpx.AsyncClient() as client:
        while True:
            body: dict[str, Any] = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
            if start_cursor:
                body["start_cursor"] = start_cursor

            async def _call() -> httpx.Response:
                return await client.post(
                    f"{NOTION_API_BASE}/search", headers=_headers(access_token), json=body, timeout=30.0
                )

            response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
            response.raise_for_status()
            page = response.json()
            pages.extend(page["results"])
            if not page.get("has_more"):
                break
            start_cursor = page.get("next_cursor")
    return pages


async def get_page_parent(access_token: str, page_id: str) -> dict[str, Any] | None:
    """`GET /v1/pages/{page_id}` — returns the page's `parent` field
    (`{"type": "page_id"|"database_id"|"workspace", ...}`), used to walk up to a known
    shared ancestor when an event fires for a page not yet in `notion_shared_page` (a
    cascaded sub-page — see core/notion/resolution.py). Returns `None` if the page is
    inaccessible or has been deleted."""
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=_headers(access_token), timeout=30.0)

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    parent: dict[str, Any] = response.json().get("parent", {})
    return parent
