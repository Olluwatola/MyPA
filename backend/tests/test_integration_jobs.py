"""Unit tests for core/integrations/jobs.py's four ARQ job functions: the Pub/Sub
pull->match->enqueue->ack cycle (unmatched address doesn't crash the batch), Gmail
notification processing (incl. the history-expired fallback and the client-side
STARRED/IMPORTANT re-check), calendar webhook processing, and watch renewal (incl. one
connection's failure not blocking the others)."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.integrations import jobs
from src.app.core.integrations.gmail import GmailHistoryExpiredError

MODULE = "src.app.core.integrations.jobs"


class _FakeSessionCM:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc_info):
        return False


def fake_local_session(db):
    """`local_session` is an async_sessionmaker — callable, returning an async context
    manager. This stands in for `async with local_session() as db:` in jobs.py."""
    return lambda: _FakeSessionCM(db)


def make_connection_row(**overrides) -> SimpleNamespace:
    defaults = {
        "id": uuid7(),
        "user_id": uuid7(),
        "type": "email",
        "provider": "google",
        "access_token": "encrypted-access",
        "connected_at": datetime.now(UTC),
        "external_account_identifier": "person@example.com",
        "refresh_token": "encrypted-refresh",
        "token_expires_at": None,
        "scopes": "scope-a scope-b",
        "revoked_at": None,
        "watch_channel_id": None,
        "watch_resource_id": None,
        "watch_expires_at": None,
        "history_id": None,
        "channel_token": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestPullGmailPubsubNotifications:
    @pytest.mark.asyncio
    async def test_no_messages_is_a_no_op(self, mock_db):
        with (
            patch(f"{MODULE}.pull_messages", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.ack_messages", new=AsyncMock()) as mock_ack,
        ):
            await jobs.pull_gmail_pubsub_notifications(ctx={"redis": AsyncMock()})

        mock_ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_matched_address_enqueues_and_unmatched_is_skipped_not_crashed(self, mock_db):
        connection_id = uuid7()
        messages = [
            {"ack_id": "ack-1", "data": json.dumps({"emailAddress": "known@example.com", "historyId": "100"}).encode()},
            {
                "ack_id": "ack-2",
                "data": json.dumps({"emailAddress": "unknown@example.com", "historyId": "200"}).encode(),
            },
            {"ack_id": "ack-3", "data": b"not-json-at-all"},
        ]
        mock_redis = AsyncMock()

        with (
            patch(f"{MODULE}.pull_messages", new=AsyncMock(return_value=messages)),
            patch(f"{MODULE}.ack_messages", new=AsyncMock()) as mock_ack,
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
        ):
            mock_crud.get = AsyncMock(side_effect=[{"id": connection_id}, None])

            await jobs.pull_gmail_pubsub_notifications(ctx={"redis": mock_redis})

        # All three are acked regardless of match outcome — at-least-once redelivery is
        # fine since downstream processing is idempotent on history_id.
        mock_ack.assert_called_once_with(["ack-1", "ack-2", "ack-3"])
        mock_redis.enqueue_job.assert_called_once_with("process_gmail_notification", str(connection_id), "100")


class TestProcessGmailNotification:
    @pytest.mark.asyncio
    async def test_missing_connection_is_a_no_op(self, mock_db):
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
        ):
            mock_crud.get = AsyncMock(return_value=None)
            await jobs.process_gmail_notification(ctx={}, connection_id=str(uuid7()), new_history_id="1")

        mock_pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoked_connection_is_a_no_op(self, mock_db):
        connection = {"id": uuid7(), "revoked_at": datetime.now(UTC)}
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            await jobs.process_gmail_notification(ctx={}, connection_id=str(uuid7()), new_history_id="1")

        mock_pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_history_delta_re_checks_labels_client_side(self, mock_db):
        """A history delta doesn't respect gmail_list_messages's q= filter — only the
        candidate actually carrying STARRED/IMPORTANT should reach the pipeline."""
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None, "history_id": "50"}
        history_entries = [
            {"messagesAdded": [{"message": {"id": "m1"}}]},
            {"messagesAdded": [{"message": {"id": "m2"}}]},
        ]
        messages_by_id = {
            "m1": {"id": "m1", "labelIds": ["STARRED"]},
            "m2": {"id": "m2", "labelIds": ["INBOX"]},
        }

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_history", new=AsyncMock(return_value=history_entries)),
            patch(f"{MODULE}.gmail_get_message", new=AsyncMock(side_effect=lambda token, mid: messages_by_id[mid])),
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            mock_crud.update = AsyncMock()

            await jobs.process_gmail_notification(ctx={}, connection_id=str(connection["id"]), new_history_id="51")

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs["source_type"] == "email"
        assert mock_pipeline.call_args.kwargs["embed"] is True
        mock_crud.update.assert_called_once()
        assert mock_crud.update.call_args.kwargs["object"]["history_id"] == "51"

    @pytest.mark.asyncio
    async def test_expired_history_falls_back_to_list_messages(self, mock_db):
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None, "history_id": "50"}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_history", new=AsyncMock(side_effect=GmailHistoryExpiredError("expired"))),
            patch(f"{MODULE}.gmail_list_messages", new=AsyncMock(return_value=[{"id": "m9"}])) as mock_list_messages,
            patch(f"{MODULE}.gmail_get_message", new=AsyncMock(return_value={"id": "m9", "labelIds": ["IMPORTANT"]})),
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            mock_crud.update = AsyncMock()

            await jobs.process_gmail_notification(ctx={}, connection_id=str(connection["id"]), new_history_id="99")

        mock_list_messages.assert_called_once()
        mock_pipeline.assert_called_once()


class TestProcessCalendarWebhook:
    @pytest.mark.asyncio
    async def test_missing_connection_is_a_no_op(self, mock_db):
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
        ):
            mock_crud.get = AsyncMock(return_value=None)
            await jobs.process_calendar_webhook(ctx={}, connection_id=str(uuid7()))

        mock_pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_lists_events_and_runs_pipeline_without_embedding(self, mock_db):
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None}
        events = [{"summary": "Standup"}, {"summary": "1:1"}]

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=events)) as mock_list_events,
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
        ):
            mock_crud.get = AsyncMock(return_value=connection)

            await jobs.process_calendar_webhook(ctx={}, connection_id=str(connection["id"]))

        mock_list_events.assert_called_once()
        assert mock_pipeline.call_count == 2
        for call in mock_pipeline.call_args_list:
            assert call.kwargs["source_type"] == "calendar"
            assert call.kwargs["embed"] is False


class TestRenewWatchesBeforeExpiry:
    @pytest.mark.asyncio
    async def test_renews_email_and_calendar_watches_independently(self, mock_db):
        email_row = make_connection_row(type="email")
        calendar_row = make_connection_row(type="calendar")
        mock_db.execute = AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [email_row, calendar_row]))
        )

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(
                f"{MODULE}.gmail_watch", new=AsyncMock(return_value={"historyId": "500", "expiration": "9999999999999"})
            ),
            patch(
                f"{MODULE}.calendar_watch",
                new=AsyncMock(return_value={"resourceId": "res-9", "expiration": "9999999999999"}),
            ),
            patch(f"{MODULE}.encrypt_token", return_value="encrypted-channel-token"),
        ):
            mock_crud.update = AsyncMock()

            await jobs.renew_watches_before_expiry(ctx={})

        assert mock_crud.update.call_count == 2
        email_update = mock_crud.update.call_args_list[0].kwargs["object"]
        assert email_update["history_id"] == "500"
        calendar_update = mock_crud.update.call_args_list[1].kwargs["object"]
        assert calendar_update["watch_resource_id"] == "res-9"
        assert calendar_update["channel_token"] == "encrypted-channel-token"

    @pytest.mark.asyncio
    async def test_one_connections_failure_does_not_block_the_others(self, mock_db):
        failing_row = make_connection_row(type="email")
        healthy_row = make_connection_row(type="email")
        mock_db.execute = AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [failing_row, healthy_row]))
        )

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(
                f"{MODULE}.get_valid_access_token",
                new=AsyncMock(side_effect=[RuntimeError("token refresh failed"), "access-token"]),
            ),
            patch(
                f"{MODULE}.gmail_watch", new=AsyncMock(return_value={"historyId": "1", "expiration": "9999999999999"})
            ),
        ):
            mock_crud.update = AsyncMock()

            await jobs.renew_watches_before_expiry(ctx={})

        # The healthy row still got renewed despite the failing row raising.
        mock_crud.update.assert_called_once()
