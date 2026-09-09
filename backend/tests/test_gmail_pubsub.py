"""Unit tests for core/integrations/pubsub.py — the google-cloud-pubsub SDK wrapper
(the one deliberate SDK exception to this codebase's hand-roll-httpx convention). The
blocking SubscriberClient itself is mocked; pull/ack request shape and the
anyio.to_thread wrapping are under test."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.app.core.integrations import pubsub


@pytest.fixture(autouse=True)
def reset_subscriber_singleton():
    pubsub._subscriber = None
    yield
    pubsub._subscriber = None


def make_pull_response(messages: list[tuple[str, bytes, dict]]) -> SimpleNamespace:
    received = [
        SimpleNamespace(ack_id=ack_id, message=SimpleNamespace(data=data, attributes=attrs))
        for ack_id, data, attrs in messages
    ]
    return SimpleNamespace(received_messages=received)


class TestPullMessages:
    @pytest.mark.asyncio
    async def test_returns_parsed_messages(self):
        mock_client = MagicMock()
        mock_client.pull.return_value = make_pull_response(
            [("ack-1", b'{"emailAddress": "a@example.com"}', {"k": "v"})]
        )

        with patch.object(pubsub.pubsub_v1, "SubscriberClient", return_value=mock_client):
            messages = await pubsub.pull_messages(max_messages=5)

        assert len(messages) == 1
        assert messages[0]["ack_id"] == "ack-1"
        assert messages[0]["data"] == b'{"emailAddress": "a@example.com"}'
        assert messages[0]["attributes"] == {"k": "v"}
        assert mock_client.pull.call_args.kwargs["request"]["max_messages"] == 5

    @pytest.mark.asyncio
    async def test_no_messages_returns_empty_list(self):
        mock_client = MagicMock()
        mock_client.pull.return_value = make_pull_response([])

        with patch.object(pubsub.pubsub_v1, "SubscriberClient", return_value=mock_client):
            messages = await pubsub.pull_messages()

        assert messages == []

    @pytest.mark.asyncio
    async def test_subscriber_client_is_reused_across_calls(self):
        mock_client = MagicMock()
        mock_client.pull.return_value = make_pull_response([])

        with patch.object(pubsub.pubsub_v1, "SubscriberClient", return_value=mock_client) as mock_ctor:
            await pubsub.pull_messages()
            await pubsub.pull_messages()

        mock_ctor.assert_called_once()


class TestAckMessages:
    @pytest.mark.asyncio
    async def test_acknowledges_given_ack_ids(self):
        mock_client = MagicMock()
        with patch.object(pubsub.pubsub_v1, "SubscriberClient", return_value=mock_client):
            await pubsub.ack_messages(["ack-1", "ack-2"])

        assert mock_client.acknowledge.call_args.kwargs["request"]["ack_ids"] == ["ack-1", "ack-2"]

    @pytest.mark.asyncio
    async def test_empty_ack_ids_is_a_no_op(self):
        mock_client = MagicMock()
        with patch.object(pubsub.pubsub_v1, "SubscriberClient", return_value=mock_client):
            await pubsub.ack_messages([])

        mock_client.acknowledge.assert_not_called()
