"""Gmail API calls — plain `httpx`, per-user-token calls (no SDK-vs-hand-roll tension
for these; only the Pub/Sub client itself gets the SDK exception, see pubsub.py).
"""

import base64
from typing import Any

import httpx

from ..utils.http_retry import execute_with_retry

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Concrete, correct ingestion query — real recent, flagged mail only, not the whole inbox.
EMAIL_INGESTION_QUERY = "newer_than:14d (is:starred OR is:important)"

# A history delta doesn't respect the `is:starred OR is:important` filter above — the
# caller re-checks each candidate against these client-side (see jobs.py).
TARGET_LABEL_IDS = {"STARRED", "IMPORTANT"}

# Widened vs the LLM providers' 429-only policy — safe here since every call below is
# either an idempotent GET or a watch/stop call, unlike a billable LLM completion.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503})


class GmailHistoryExpiredError(Exception):
    """Raised on a 404 from users.history.list — history IDs retain only ~1 week; the
    caller falls back to a fresh `gmail_list_messages` call."""


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def _get(access_token: str, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.get(
                f"{GMAIL_API_BASE}{path}", headers=_headers(access_token), params=params, timeout=30.0
            )

        return await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)


async def _post(access_token: str, path: str, json: dict[str, Any] | None = None) -> httpx.Response:
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.post(f"{GMAIL_API_BASE}{path}", headers=_headers(access_token), json=json, timeout=30.0)

        return await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)


async def gmail_watch(access_token: str, topic_name: str) -> dict[str, Any]:
    """Registers (or renews) a `users.watch()` push subscription. Returns Gmail's
    response, which carries `historyId` and `expiration` (epoch ms)."""
    response = await _post(access_token, "/watch", json={"topicName": topic_name, "labelIds": ["INBOX"]})
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return data


async def gmail_stop_watch(access_token: str) -> None:
    response = await _post(access_token, "/stop")
    response.raise_for_status()


async def gmail_get_profile(access_token: str) -> dict[str, Any]:
    """Returns Gmail's profile, notably `emailAddress` — used as the connection's
    `external_account_identifier`."""
    response = await _get(access_token, "/profile")
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return data


async def gmail_list_messages(access_token: str, query: str = EMAIL_INGESTION_QUERY) -> list[dict[str, Any]]:
    response = await _get(access_token, "/messages", params={"q": query})
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    messages: list[dict[str, Any]] = data.get("messages", [])
    return messages


async def gmail_get_message(access_token: str, message_id: str) -> dict[str, Any]:
    response = await _get(access_token, f"/messages/{message_id}", params={"format": "full"})
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return data


async def gmail_list_history(access_token: str, start_history_id: str) -> list[dict[str, Any]]:
    response = await _get(
        access_token, "/history", params={"startHistoryId": start_history_id, "historyTypes": "messageAdded"}
    )
    if response.status_code == 404:
        raise GmailHistoryExpiredError(f"History ID {start_history_id} has expired (>~1 week retention).")
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    history: list[dict[str, Any]] = data.get("history", [])
    return history


def message_matches_ingestion_labels(message: dict[str, Any]) -> bool:
    """Client-side re-check that a history-delta candidate actually carries a
    STARRED/IMPORTANT label — a history delta doesn't respect the `q=` filter used by
    `gmail_list_messages`."""
    label_ids = set(message.get("labelIds", []) or [])
    return bool(label_ids & TARGET_LABEL_IDS)


def parse_gmail_message(message: dict[str, Any]) -> str:
    """Extracts headers + decoded body into one content string for the extraction
    pipeline."""
    payload = message.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
    subject = headers.get("Subject", "")
    sender = headers.get("From", "")
    body_text = _extract_body(payload)

    return "\n".join([f"From: {sender}", f"Subject: {subject}", "", body_text])


def _extract_body(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_body(payload["body"]["data"])

    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _decode_body(part["body"]["data"])

    for part in payload.get("parts", []) or []:
        nested = _extract_body(part)
        if nested:
            return nested

    return ""


def _decode_body(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
