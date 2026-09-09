"""Google Calendar API calls — plain `httpx`, same retry pattern as gmail.py."""

from datetime import datetime
from typing import Any

import httpx

from ..utils.http_retry import execute_with_retry

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
CALENDAR_EVENTS_BASE = f"{CALENDAR_API_BASE}/calendars/primary/events"

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503})


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def calendar_watch(access_token: str, channel_id: str, channel_token: str, webhook_url: str) -> dict[str, Any]:
    """Registers (or renews) an `events.watch()` push channel. Returns Google's
    response, carrying `resourceId` and `expiration` (epoch ms) — persisted alongside
    `channel_id`/`channel_token` on the connection row.

    The webhook URL is read here, at registration time, never at request-handling time
    (see api/v1/webhooks_google_calendar.py) — identical code whether it came from a
    tunnel or a real domain."""
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.post(
                f"{CALENDAR_EVENTS_BASE}/watch",
                headers=_headers(access_token),
                json={"id": channel_id, "type": "web_hook", "address": webhook_url, "token": channel_token},
                timeout=30.0,
            )

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return data


async def calendar_stop_watch(access_token: str, channel_id: str, resource_id: str) -> None:
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.post(
                f"{CALENDAR_API_BASE}/channels/stop",
                headers=_headers(access_token),
                json={"id": channel_id, "resourceId": resource_id},
                timeout=30.0,
            )

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()


async def calendar_list_events(access_token: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
    """`singleEvents=true` so Google pre-expands recurring events — no hand-rolled RRULE
    math needed."""
    async with httpx.AsyncClient() as client:

        async def _call() -> httpx.Response:
            return await client.get(
                CALENDAR_EVENTS_BASE,
                headers=_headers(access_token),
                params={
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                },
                timeout=30.0,
            )

        response = await execute_with_retry(_call, retryable_status_codes=RETRYABLE_STATUS_CODES)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    events: list[dict[str, Any]] = data.get("items", [])
    return events


def parse_calendar_event(event: dict[str, Any]) -> str:
    summary = event.get("summary", "(no title)")
    description = event.get("description", "")
    location = event.get("location", "")
    start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
    end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")
    attendees = ", ".join(a.get("email", "") for a in event.get("attendees", []) if a.get("email"))

    parts = [f"Event: {summary}", f"When: {start} - {end}"]
    if location:
        parts.append(f"Location: {location}")
    if attendees:
        parts.append(f"Attendees: {attendees}")
    if description:
        parts.append(f"Description: {description}")
    return "\n".join(parts)
