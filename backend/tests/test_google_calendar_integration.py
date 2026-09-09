"""Unit tests for core/integrations/google_calendar.py: request shape and event
parsing. Google's endpoints are mocked via httpx.AsyncClient patches."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.app.core.integrations.google_calendar import (
    calendar_list_events,
    calendar_stop_watch,
    calendar_watch,
    parse_calendar_event,
)


def make_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    # `request=` is required for `.raise_for_status()` to work on a manually-constructed
    # Response — a real httpx send cycle sets it automatically, a mocked one doesn't.
    return httpx.Response(
        status_code=status_code, json=json_body or {}, request=httpx.Request("GET", "https://example.com")
    )


class TestCalendarWatch:
    @pytest.mark.asyncio
    async def test_registers_web_hook_channel(self):
        mock_post = AsyncMock(return_value=make_response(200, {"resourceId": "res-1", "expiration": "999999999"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await calendar_watch("token", "chan-1", "secret-token", "https://example.com/webhook")

        assert result["resourceId"] == "res-1"
        body = mock_post.call_args.kwargs["json"]
        assert body["id"] == "chan-1"
        assert body["type"] == "web_hook"
        assert body["address"] == "https://example.com/webhook"
        assert body["token"] == "secret-token"

    @pytest.mark.asyncio
    async def test_stop_watch_sends_channel_and_resource_id(self):
        mock_post = AsyncMock(return_value=make_response(200, {}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            await calendar_stop_watch("token", "chan-1", "res-1")

        body = mock_post.call_args.kwargs["json"]
        assert body == {"id": "chan-1", "resourceId": "res-1"}


class TestCalendarListEvents:
    @pytest.mark.asyncio
    async def test_requests_single_events_expanded(self):
        mock_get = AsyncMock(return_value=make_response(200, {"items": [{"id": "e1"}]}))
        now = datetime.now(UTC)
        with patch.object(httpx.AsyncClient, "get", mock_get):
            events = await calendar_list_events("token", now, now + timedelta(days=14))

        assert events == [{"id": "e1"}]
        assert mock_get.call_args.kwargs["params"]["singleEvents"] == "true"

    @pytest.mark.asyncio
    async def test_no_items_key_returns_empty_list(self):
        mock_get = AsyncMock(return_value=make_response(200, {}))
        now = datetime.now(UTC)
        with patch.object(httpx.AsyncClient, "get", mock_get):
            events = await calendar_list_events("token", now, now + timedelta(days=14))

        assert events == []


class TestParseCalendarEvent:
    def test_full_event(self):
        event = {
            "summary": "Team sync",
            "description": "Weekly check-in",
            "location": "Room 4",
            "start": {"dateTime": "2026-09-10T10:00:00Z"},
            "end": {"dateTime": "2026-09-10T10:30:00Z"},
            "attendees": [{"email": "a@example.com"}, {"email": "b@example.com"}],
        }

        content = parse_calendar_event(event)

        assert "Team sync" in content
        assert "Room 4" in content
        assert "a@example.com" in content
        assert "Weekly check-in" in content

    def test_minimal_event_with_all_day_dates(self):
        event = {"start": {"date": "2026-09-10"}, "end": {"date": "2026-09-11"}}

        content = parse_calendar_event(event)

        assert "(no title)" in content
        assert "2026-09-10" in content
