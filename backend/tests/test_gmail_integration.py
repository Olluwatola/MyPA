"""Unit tests for core/integrations/gmail.py: request shape, the history-expired 404
fallback signal, the client-side STARRED/IMPORTANT re-check, and message parsing.
Google's endpoints are mocked via httpx.AsyncClient patches."""

import base64
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.app.core.integrations.gmail import (
    EMAIL_INGESTION_QUERY,
    GmailHistoryExpiredError,
    gmail_get_message,
    gmail_get_profile,
    gmail_list_history,
    gmail_list_messages,
    gmail_stop_watch,
    gmail_watch,
    message_matches_ingestion_labels,
    parse_gmail_message,
)


def make_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    # `request=` is required for `.raise_for_status()` to work on a manually-constructed
    # Response — a real httpx send cycle sets it automatically, a mocked one doesn't.
    return httpx.Response(
        status_code=status_code, json=json_body or {}, request=httpx.Request("GET", "https://example.com")
    )


class TestGmailWatch:
    @pytest.mark.asyncio
    async def test_watch_posts_topic_name(self):
        mock_post = AsyncMock(return_value=make_response(200, {"historyId": "123", "expiration": "999999999"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await gmail_watch("token", "projects/p/topics/t")

        assert result["historyId"] == "123"
        assert mock_post.call_args.kwargs["json"]["topicName"] == "projects/p/topics/t"

    @pytest.mark.asyncio
    async def test_stop_watch_calls_stop_endpoint(self):
        mock_post = AsyncMock(return_value=make_response(200, {}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            await gmail_stop_watch("token")

        assert mock_post.call_args.args[0].endswith("/stop")


class TestGmailGetProfile:
    @pytest.mark.asyncio
    async def test_returns_email_address(self):
        mock_get = AsyncMock(return_value=make_response(200, {"emailAddress": "person@example.com"}))
        with patch.object(httpx.AsyncClient, "get", mock_get):
            profile = await gmail_get_profile("token")

        assert profile["emailAddress"] == "person@example.com"


class TestGmailListMessages:
    @pytest.mark.asyncio
    async def test_default_query_is_ingestion_query(self):
        mock_get = AsyncMock(return_value=make_response(200, {"messages": [{"id": "m1"}]}))
        with patch.object(httpx.AsyncClient, "get", mock_get):
            messages = await gmail_list_messages("token")

        assert messages == [{"id": "m1"}]
        assert mock_get.call_args.kwargs["params"]["q"] == EMAIL_INGESTION_QUERY

    @pytest.mark.asyncio
    async def test_no_messages_key_returns_empty_list(self):
        mock_get = AsyncMock(return_value=make_response(200, {}))
        with patch.object(httpx.AsyncClient, "get", mock_get):
            messages = await gmail_list_messages("token")

        assert messages == []


class TestGmailGetMessage:
    @pytest.mark.asyncio
    async def test_requests_full_format(self):
        mock_get = AsyncMock(return_value=make_response(200, {"id": "m1", "labelIds": ["STARRED"]}))
        with patch.object(httpx.AsyncClient, "get", mock_get):
            message = await gmail_get_message("token", "m1")

        assert message["id"] == "m1"
        assert mock_get.call_args.kwargs["params"]["format"] == "full"


class TestGmailListHistory:
    @pytest.mark.asyncio
    async def test_returns_history_entries(self):
        mock_get = AsyncMock(return_value=make_response(200, {"history": [{"id": "1"}]}))
        with patch.object(httpx.AsyncClient, "get", mock_get):
            history = await gmail_list_history("token", "1000")

        assert history == [{"id": "1"}]

    @pytest.mark.asyncio
    async def test_404_raises_history_expired_error(self):
        """History IDs retain only ~1 week — the caller falls back to a fresh
        gmail_list_messages call on this signal."""
        mock_get = AsyncMock(return_value=make_response(404, {}))
        with patch.object(httpx.AsyncClient, "get", mock_get):
            with pytest.raises(GmailHistoryExpiredError):
                await gmail_list_history("token", "expired-history-id")


class TestMessageMatchesIngestionLabels:
    def test_starred_matches(self):
        assert message_matches_ingestion_labels({"labelIds": ["STARRED", "INBOX"]}) is True

    def test_important_matches(self):
        assert message_matches_ingestion_labels({"labelIds": ["IMPORTANT"]}) is True

    def test_neither_does_not_match(self):
        assert message_matches_ingestion_labels({"labelIds": ["INBOX", "UNREAD"]}) is False

    def test_missing_label_ids_does_not_match(self):
        assert message_matches_ingestion_labels({}) is False


class TestParseGmailMessage:
    def test_extracts_headers_and_plain_text_body(self):
        body_text = "Hello there"
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode().rstrip("=")
        message = {
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Test subject"},
                    {"name": "From", "value": "sender@example.com"},
                ],
                "body": {"data": encoded},
            }
        }

        content = parse_gmail_message(message)

        assert "Test subject" in content
        assert "sender@example.com" in content
        assert "Hello there" in content

    def test_extracts_nested_multipart_plain_text(self):
        body_text = "Nested body"
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode().rstrip("=")
        message = {
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [{"name": "Subject", "value": "S"}, {"name": "From", "value": "f@example.com"}],
                "parts": [
                    {"mimeType": "text/html", "body": {"data": "aGVsbG8="}},
                    {"mimeType": "text/plain", "body": {"data": encoded}},
                ],
            }
        }

        content = parse_gmail_message(message)

        assert "Nested body" in content
