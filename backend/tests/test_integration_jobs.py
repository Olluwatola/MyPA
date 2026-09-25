"""Unit tests for core/integrations/jobs.py's ARQ job functions: the Pub/Sub
pull->match->enqueue->ack cycle (per-message acking, unmatched address doesn't crash the
batch, a failed enqueue leaves that one message unacked rather than crashing the rest),
Gmail notification processing (incl. the history-expired fallback, the client-side
STARRED/IMPORTANT re-check, per-item dedup, and retry-with-backoff on a transient
failure), calendar webhook processing (same dedup/retry shape), onboarding bulk ingestion
(incl. per-item fault isolation, dedup, retry-before-exhausting, and the outright-failure
reset), and watch renewal (incl. one connection's failure not blocking the others)."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest
from arq import Retry
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


# Every test that exercises a per-item ingestion loop patches these two out — jobs.py
# calls them by name (`from .dedup import is_item_unchanged, mark_item_synced`), so an
# unpatched call would hit the real dedup module against a bare Mock(spec=AsyncSession).
# `with (...)` context-manager groups can't unpack a tuple of patches, so each call site
# below repeats the pair of lines rather than sharing this as a helper.


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

        # Each message is acked individually, right after its own handling decision —
        # not batched at the end — regardless of match outcome.
        mock_ack.assert_has_calls([call(["ack-1"]), call(["ack-2"]), call(["ack-3"])])
        assert mock_ack.call_count == 3
        mock_redis.enqueue_job.assert_called_once_with(
            "process_gmail_notification", str(connection_id), "100", _job_id=f"gmail-notif-{connection_id}-100"
        )

    @pytest.mark.asyncio
    async def test_enqueue_failure_leaves_message_unacked_and_does_not_crash_batch(self, mock_db):
        connection_id = uuid7()
        messages = [
            {"ack_id": "ack-1", "data": json.dumps({"emailAddress": "a@example.com", "historyId": "1"}).encode()},
            {"ack_id": "ack-2", "data": json.dumps({"emailAddress": "b@example.com", "historyId": "2"}).encode()},
        ]
        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock(side_effect=[RuntimeError("redis down"), None])

        with (
            patch(f"{MODULE}.pull_messages", new=AsyncMock(return_value=messages)),
            patch(f"{MODULE}.ack_messages", new=AsyncMock()) as mock_ack,
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
        ):
            mock_crud.get = AsyncMock(side_effect=[{"id": connection_id}, {"id": connection_id}])

            # Does not raise — a failed enqueue is logged and the batch continues.
            await jobs.pull_gmail_pubsub_notifications(ctx={"redis": mock_redis})

        # Only the second message (whose enqueue succeeded) gets acked.
        mock_ack.assert_called_once_with(["ack-2"])


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
            patch(
                f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock(return_value={"id": uuid7()})
            ) as mock_pipeline,
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(False, None))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()),
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
            patch(
                f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock(return_value={"id": uuid7()})
            ) as mock_pipeline,
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(False, None))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()),
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            mock_crud.update = AsyncMock()

            await jobs.process_gmail_notification(ctx={}, connection_id=str(connection["id"]), new_history_id="99")

        mock_list_messages.assert_called_once()
        mock_pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_unchanged_message_skips_pipeline_and_mark_synced(self, mock_db):
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None, "history_id": "50"}
        history_entries = [{"messagesAdded": [{"message": {"id": "m1"}}]}]

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_history", new=AsyncMock(return_value=history_entries)),
            patch(f"{MODULE}.gmail_get_message", new=AsyncMock(return_value={"id": "m1", "labelIds": ["STARRED"]})),
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(True, {"id": uuid7()}))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()) as mock_mark_synced,
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            mock_crud.update = AsyncMock()

            await jobs.process_gmail_notification(ctx={}, connection_id=str(connection["id"]), new_history_id="51")

        mock_pipeline.assert_not_called()
        mock_mark_synced.assert_not_called()

    @pytest.mark.asyncio
    async def test_changed_message_marks_synced_with_returned_record_id(self, mock_db):
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None, "history_id": "50"}
        history_entries = [{"messagesAdded": [{"message": {"id": "m1"}}]}]
        record_id = uuid7()
        existing_row = {"id": uuid7(), "content_fingerprint": "stale"}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_history", new=AsyncMock(return_value=history_entries)),
            patch(f"{MODULE}.gmail_get_message", new=AsyncMock(return_value={"id": "m1", "labelIds": ["STARRED"]})),
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock(return_value={"id": record_id})),
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(False, existing_row))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()) as mock_mark_synced,
        ):
            mock_crud.get = AsyncMock(return_value=connection)
            mock_crud.update = AsyncMock()

            await jobs.process_gmail_notification(ctx={}, connection_id=str(connection["id"]), new_history_id="51")

        mock_mark_synced.assert_called_once()
        # Trailing two positional args are (memory_record_id, existing_row) — the latter
        # is the already-fetched row from is_item_unchanged, passed through rather than
        # re-fetched (Finding 3).
        assert mock_mark_synced.call_args.args[-2] == record_id
        assert mock_mark_synced.call_args.args[-1] is existing_row

    @pytest.mark.asyncio
    async def test_transient_failure_raises_retry_with_backoff(self, mock_db):
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None, "history_id": "50"}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(side_effect=RuntimeError("token refresh failed"))),
        ):
            mock_crud.get = AsyncMock(return_value=connection)

            with pytest.raises(Retry) as exc_info:
                await jobs.process_gmail_notification(
                    ctx={"job_try": 2}, connection_id=str(connection["id"]), new_history_id="51"
                )

        assert exc_info.value.defer_score == 120_000  # 60s base * 2^(2-1), in ms


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
        events = [{"id": "e1", "summary": "Standup"}, {"id": "e2", "summary": "1:1"}]

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=events)) as mock_list_events,
            patch(
                f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock(return_value={"id": uuid7()})
            ) as mock_pipeline,
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(False, None))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()),
        ):
            mock_crud.get = AsyncMock(return_value=connection)

            await jobs.process_calendar_webhook(ctx={}, connection_id=str(connection["id"]))

        mock_list_events.assert_called_once()
        assert mock_pipeline.call_count == 2
        for call_args in mock_pipeline.call_args_list:
            assert call_args.kwargs["source_type"] == "calendar"
            assert call_args.kwargs["embed"] is False

    @pytest.mark.asyncio
    async def test_unchanged_event_skips_pipeline_and_mark_synced(self, mock_db):
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None}
        events = [{"id": "e1", "summary": "Standup"}]

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=events)),
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(True, {"id": uuid7()}))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()) as mock_mark_synced,
        ):
            mock_crud.get = AsyncMock(return_value=connection)

            await jobs.process_calendar_webhook(ctx={}, connection_id=str(connection["id"]))

        mock_pipeline.assert_not_called()
        mock_mark_synced.assert_not_called()

    @pytest.mark.asyncio
    async def test_changed_event_marks_synced_with_returned_record_id(self, mock_db):
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None}
        events = [{"id": "e1", "summary": "Standup"}]
        record_id = uuid7()
        existing_row = {"id": uuid7(), "content_fingerprint": "stale"}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=events)),
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock(return_value={"id": record_id})),
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(False, existing_row))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()) as mock_mark_synced,
        ):
            mock_crud.get = AsyncMock(return_value=connection)

            await jobs.process_calendar_webhook(ctx={}, connection_id=str(connection["id"]))

        mock_mark_synced.assert_called_once()
        assert mock_mark_synced.call_args.args[-2] == record_id
        assert mock_mark_synced.call_args.args[-1] is existing_row

    @pytest.mark.asyncio
    async def test_two_idless_events_both_processed_not_collided(self, mock_db):
        """Two events with no "id" must not collide on a shared fallback key — both get
        processed (fault-isolated from dedup entirely) instead of the second silently
        overwriting the first's ingestion_sync tracking."""
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None}
        events = [{"summary": "Untitled A"}, {"summary": "Untitled B"}]

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=events)),
            patch(
                f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock(return_value={"id": uuid7()})
            ) as mock_pipeline,
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock()) as mock_is_unchanged,
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()) as mock_mark_synced,
        ):
            mock_crud.get = AsyncMock(return_value=connection)

            await jobs.process_calendar_webhook(ctx={}, connection_id=str(connection["id"]))

        assert mock_pipeline.call_count == 2
        mock_is_unchanged.assert_not_called()
        mock_mark_synced.assert_not_called()

    @pytest.mark.asyncio
    async def test_transient_failure_raises_retry_with_backoff(self, mock_db):
        connection = {"id": uuid7(), "user_id": uuid7(), "revoked_at": None}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(side_effect=RuntimeError("token refresh failed"))),
        ):
            mock_crud.get = AsyncMock(return_value=connection)

            with pytest.raises(Retry) as exc_info:
                await jobs.process_calendar_webhook(ctx={"job_try": 1}, connection_id=str(connection["id"]))

        assert exc_info.value.defer_score == 60_000  # 60s base * 2^(1-1), in ms


class TestRunOnboardingIngestion:
    @pytest.mark.asyncio
    async def test_missing_connection_resets_to_not_started(self, mock_db):
        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_conn_crud,
            patch(f"{MODULE}.crud_users") as mock_users_crud,
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
        ):
            # email connection exists, calendar connection is missing.
            mock_conn_crud.get = AsyncMock(side_effect=[{"id": uuid7()}, None])
            mock_users_crud.update = AsyncMock()

            await jobs.run_onboarding_ingestion(ctx={}, user_id=str(uuid7()))

        mock_pipeline.assert_not_called()
        mock_users_crud.update.assert_called_once()
        assert mock_users_crud.update.call_args.kwargs["object"] == {"onboarding_status": "not_started"}

    @pytest.mark.asyncio
    async def test_a_failing_item_does_not_abort_the_batch(self, mock_db):
        """A failing 2nd Gmail message doesn't abort the run — the first message still
        reaches the pipeline and the job still completes to `ready`."""
        from src.app.schemas.goal import GoalSynthesisResult, SuggestedGoal

        connection = {"id": uuid7()}
        record_id = uuid7()

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_conn_crud,
            patch(f"{MODULE}.crud_users") as mock_users_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_messages", new=AsyncMock(return_value=[{"id": "m1"}, {"id": "m2"}])),
            patch(f"{MODULE}.gmail_get_message", new=AsyncMock(side_effect=lambda token, mid: {"id": mid})),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=[])),
            patch(
                f"{MODULE}.run_memory_extraction_pipeline",
                new=AsyncMock(side_effect=[{"summary": "s1", "id": record_id}, Exception("boom")]),
            ) as mock_pipeline,
            patch(
                f"{MODULE}.call_goal_synthesis_llm",
                new=AsyncMock(
                    return_value=GoalSynthesisResult(suggested_goals=[SuggestedGoal(title="Cross-item goal")])
                ),
            ) as mock_synthesis,
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(False, None))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()),
            patch(
                f"{MODULE}.drop_existing_goal_suggestions",
                new=AsyncMock(side_effect=lambda db, user_id, suggestions: suggestions),
            ),
        ):
            mock_conn_crud.get = AsyncMock(return_value=connection)
            mock_users_crud.update = AsyncMock()

            await jobs.run_onboarding_ingestion(ctx={}, user_id=str(uuid7()))

        assert mock_pipeline.call_count == 2
        mock_synthesis.assert_called_once_with([("email", "s1")])
        mock_users_crud.update.assert_called_once()
        update_object = mock_users_crud.update.call_args.kwargs["object"]
        assert update_object["onboarding_status"] == "ready"
        assert update_object["onboarding_suggested_goals"] == [
            {"title": "Cross-item goal", "description": None, "horizon": None}
        ]

    @pytest.mark.asyncio
    async def test_unchanged_item_recovers_summary_instead_of_being_dropped(self, mock_db):
        """One of two Gmail messages is already synced and unchanged (dedup-skipped) — it
        must NOT just vanish from `summaries`: its previously-extracted summary is
        recovered via the `ingestion_sync` row's `memory_record_id` and still reaches the
        synthesis call, alongside the freshly-processed second message (Finding 1)."""
        from src.app.schemas.goal import GoalSynthesisResult

        connection = {"id": uuid7()}
        record_id = uuid7()
        recovered_memory_record_id = uuid7()
        existing_row = {"id": uuid7(), "memory_record_id": recovered_memory_record_id}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_conn_crud,
            patch(f"{MODULE}.crud_users") as mock_users_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_messages", new=AsyncMock(return_value=[{"id": "m1"}, {"id": "m2"}])),
            patch(f"{MODULE}.gmail_get_message", new=AsyncMock(side_effect=lambda token, mid: {"id": mid})),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(side_effect=[(True, existing_row), (False, None)])),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()),
            patch(
                f"{MODULE}.crud_memory_extraction_records",
            ) as mock_memory_records_crud,
            patch(
                f"{MODULE}.run_memory_extraction_pipeline",
                new=AsyncMock(return_value={"summary": "s2", "id": record_id}),
            ) as mock_pipeline,
            patch(
                f"{MODULE}.call_goal_synthesis_llm", new=AsyncMock(return_value=GoalSynthesisResult(suggested_goals=[]))
            ) as mock_synthesis,
        ):
            mock_conn_crud.get = AsyncMock(return_value=connection)
            mock_users_crud.update = AsyncMock()
            mock_memory_records_crud.get = AsyncMock(return_value={"summary": "recovered s1"})

            await jobs.run_onboarding_ingestion(ctx={}, user_id=str(uuid7()))

        mock_pipeline.assert_called_once()
        mock_memory_records_crud.get.assert_called_once_with(db=mock_db, id=recovered_memory_record_id)
        mock_synthesis.assert_called_once_with([("email", "recovered s1"), ("email", "s2")])

    @pytest.mark.asyncio
    async def test_retry_recovers_summaries_for_previously_synced_items(self, mock_db):
        """Simulates a retry attempt: one Gmail message and one calendar event were both
        already synced by a prior attempt (dedup hits), one Gmail message is new this
        attempt. The final synthesis call must receive summaries for ALL successfully
        processed items — the ones freshly processed this attempt AND the ones recovered
        from the prior attempt via dedup — not just the newly-processed one (Finding 1)."""
        from src.app.schemas.goal import GoalSynthesisResult

        connection = {"id": uuid7()}
        fresh_record_id = uuid7()
        recovered_email_memory_id = uuid7()
        recovered_calendar_memory_id = uuid7()
        recovered_email_row = {"id": uuid7(), "memory_record_id": recovered_email_memory_id}
        recovered_calendar_row = {"id": uuid7(), "memory_record_id": recovered_calendar_memory_id}
        recovered_summaries_by_id = {
            recovered_email_memory_id: {"summary": "prior-attempt email summary"},
            recovered_calendar_memory_id: {"summary": "prior-attempt calendar summary"},
        }

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_conn_crud,
            patch(f"{MODULE}.crud_users") as mock_users_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_messages", new=AsyncMock(return_value=[{"id": "m1"}, {"id": "m2"}])),
            patch(f"{MODULE}.gmail_get_message", new=AsyncMock(side_effect=lambda token, mid: {"id": mid})),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=[{"id": "e1"}])),
            patch(
                f"{MODULE}.is_item_unchanged",
                new=AsyncMock(
                    side_effect=[
                        (True, recovered_email_row),  # m1 — already synced on a prior attempt
                        (False, None),  # m2 — new this attempt
                        (True, recovered_calendar_row),  # e1 — already synced on a prior attempt
                    ]
                ),
            ),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()),
            patch(f"{MODULE}.crud_memory_extraction_records") as mock_memory_records_crud,
            patch(
                f"{MODULE}.run_memory_extraction_pipeline",
                new=AsyncMock(return_value={"summary": "fresh m2 summary", "id": fresh_record_id}),
            ) as mock_pipeline,
            patch(
                f"{MODULE}.call_goal_synthesis_llm", new=AsyncMock(return_value=GoalSynthesisResult(suggested_goals=[]))
            ) as mock_synthesis,
        ):
            mock_conn_crud.get = AsyncMock(return_value=connection)
            mock_users_crud.update = AsyncMock()
            mock_memory_records_crud.get = AsyncMock(side_effect=lambda db, id: recovered_summaries_by_id[id])

            await jobs.run_onboarding_ingestion(ctx={}, user_id=str(uuid7()))

        # Only m2 (the genuinely new item) reaches the extraction pipeline this attempt.
        mock_pipeline.assert_called_once()
        # But synthesis sees all three: the two recovered from the prior attempt's synced
        # rows, plus the one freshly processed now.
        mock_synthesis.assert_called_once_with(
            [
                ("email", "prior-attempt email summary"),
                ("email", "fresh m2 summary"),
                ("calendar", "prior-attempt calendar summary"),
            ]
        )

    @pytest.mark.asyncio
    async def test_empty_summaries_skips_synthesis(self, mock_db):
        connection = {"id": uuid7()}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_conn_crud,
            patch(f"{MODULE}.crud_users") as mock_users_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_messages", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.run_memory_extraction_pipeline", new=AsyncMock()) as mock_pipeline,
            patch(f"{MODULE}.call_goal_synthesis_llm", new=AsyncMock()) as mock_synthesis,
        ):
            mock_conn_crud.get = AsyncMock(return_value=connection)
            mock_users_crud.update = AsyncMock()

            await jobs.run_onboarding_ingestion(ctx={}, user_id=str(uuid7()))

        mock_pipeline.assert_not_called()
        mock_synthesis.assert_not_called()
        mock_users_crud.update.assert_called_once()
        assert mock_users_crud.update.call_args.kwargs["object"] == {
            "onboarding_status": "ready",
            "onboarding_suggested_goals": [],
        }

    @pytest.mark.asyncio
    async def test_transient_outer_failure_retries_before_exhausting(self, mock_db):
        connection = {"id": uuid7()}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_conn_crud,
            patch(f"{MODULE}.crud_users") as mock_users_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(side_effect=RuntimeError("token refresh failed"))),
        ):
            mock_conn_crud.get = AsyncMock(return_value=connection)
            mock_users_crud.update = AsyncMock()

            with pytest.raises(Retry) as exc_info:
                await jobs.run_onboarding_ingestion(ctx={"job_try": 1}, user_id=str(uuid7()))

        assert exc_info.value.defer_score == 60_000
        # Not yet exhausted (job_try=1 < ONBOARDING_MAX_TRIES=3) — the user must not see
        # onboarding_status reset to not_started on the very first transient failure.
        mock_users_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_outright_failure_resets_to_not_started(self, mock_db):
        connection = {"id": uuid7()}

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_conn_crud,
            patch(f"{MODULE}.crud_users") as mock_users_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(side_effect=RuntimeError("token refresh failed"))),
        ):
            mock_conn_crud.get = AsyncMock(return_value=connection)
            mock_users_crud.update = AsyncMock()

            # The exhausted attempt — retries are used up, the outer reset must fire.
            await jobs.run_onboarding_ingestion(ctx={"job_try": jobs.ONBOARDING_MAX_TRIES}, user_id=str(uuid7()))

        mock_users_crud.update.assert_called_once()
        assert mock_users_crud.update.call_args.kwargs["object"] == {"onboarding_status": "not_started"}


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


class TestOnboardingSuggestionDedup:
    @pytest.mark.asyncio
    async def test_suggestions_the_user_already_has_are_not_saved(self, mock_db):
        """Required proof (e), synthesis half: the stored checklist is what's left AFTER the
        'already have it' filter (e.g. a goal auto-created from an email earlier in the
        same run)."""
        from src.app.schemas.goal import GoalSynthesisResult, SuggestedGoal

        existing_dup = SuggestedGoal(title="Close the seed round")
        fresh = SuggestedGoal(title="Hire a designer")
        user_id = uuid7()

        with (
            patch(f"{MODULE}.local_session", new=fake_local_session(mock_db)),
            patch(f"{MODULE}.crud_integration_connections") as mock_conn_crud,
            patch(f"{MODULE}.crud_users") as mock_users_crud,
            patch(f"{MODULE}.get_valid_access_token", new=AsyncMock(return_value="access-token")),
            patch(f"{MODULE}.gmail_list_messages", new=AsyncMock(return_value=[{"id": "m1"}])),
            patch(f"{MODULE}.gmail_get_message", new=AsyncMock(return_value={"id": "m1"})),
            patch(f"{MODULE}.calendar_list_events", new=AsyncMock(return_value=[])),
            patch(
                f"{MODULE}.run_memory_extraction_pipeline",
                new=AsyncMock(return_value={"summary": "s1", "id": uuid7()}),
            ),
            patch(
                f"{MODULE}.call_goal_synthesis_llm",
                new=AsyncMock(return_value=GoalSynthesisResult(suggested_goals=[existing_dup, fresh])),
            ),
            patch(f"{MODULE}.is_item_unchanged", new=AsyncMock(return_value=(False, None))),
            patch(f"{MODULE}.mark_item_synced", new=AsyncMock()),
            patch(f"{MODULE}.drop_existing_goal_suggestions", new=AsyncMock(return_value=[fresh])) as mock_filter,
        ):
            mock_conn_crud.get = AsyncMock(return_value={"id": uuid7()})
            mock_users_crud.update = AsyncMock()

            await jobs.run_onboarding_ingestion(ctx={}, user_id=str(user_id))

        assert mock_filter.call_args.args[1:] == (user_id, [existing_dup, fresh])
        update_object = mock_users_crud.update.call_args.kwargs["object"]
        assert update_object["onboarding_suggested_goals"] == [
            {"title": "Hire a designer", "description": None, "horizon": None}
        ]
