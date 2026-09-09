"""Unit tests for the Calendar webhook receiver: valid/invalid channel token, unknown
channel, and the `sync` handshake no-op."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.api.v1.webhooks_google_calendar import google_calendar_webhook
from src.app.core.exceptions.http_exceptions import NotFoundException, UnauthorizedException

MODULE = "src.app.api.v1.webhooks_google_calendar"


class TestGoogleCalendarWebhook:
    @pytest.mark.asyncio
    async def test_missing_channel_id_returns_not_found(self, mock_db):
        with pytest.raises(NotFoundException):
            await google_calendar_webhook(
                db=mock_db, x_goog_channel_id=None, x_goog_channel_token="t", x_goog_resource_state="exists"
            )

    @pytest.mark.asyncio
    async def test_unknown_channel_id_returns_not_found(self, mock_db):
        with patch(f"{MODULE}.crud_integration_connections") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundException):
                await google_calendar_webhook(
                    db=mock_db,
                    x_goog_channel_id="unknown-chan",
                    x_goog_channel_token="t",
                    x_goog_resource_state="exists",
                )

    @pytest.mark.asyncio
    async def test_mismatched_token_returns_unauthorized(self, mock_db):
        connection = {"id": uuid7(), "channel_token": "encrypted-secret"}
        with (
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.decrypt_token", return_value="the-real-secret"),
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            with pytest.raises(UnauthorizedException):
                await google_calendar_webhook(
                    db=mock_db,
                    x_goog_channel_id="chan-1",
                    x_goog_channel_token="wrong-secret",
                    x_goog_resource_state="exists",
                )

    @pytest.mark.asyncio
    async def test_sync_handshake_is_a_no_op(self, mock_db):
        connection = {"id": uuid7(), "channel_token": "encrypted-secret"}
        with (
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.decrypt_token", return_value="the-real-secret"),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            mock_queue.pool.enqueue_job = AsyncMock()

            response = await google_calendar_webhook(
                db=mock_db,
                x_goog_channel_id="chan-1",
                x_goog_channel_token="the-real-secret",
                x_goog_resource_state="sync",
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_notification_enqueues_processing_job(self, mock_db):
        connection = {"id": uuid7(), "channel_token": "encrypted-secret"}
        with (
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.decrypt_token", return_value="the-real-secret"),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            mock_queue.pool.enqueue_job = AsyncMock()

            response = await google_calendar_webhook(
                db=mock_db,
                x_goog_channel_id="chan-1",
                x_goog_channel_token="the-real-secret",
                x_goog_resource_state="exists",
            )

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_called_once_with("process_calendar_webhook", str(connection["id"]))
