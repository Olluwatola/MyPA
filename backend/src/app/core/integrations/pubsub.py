"""Wraps `google.cloud.pubsub_v1.SubscriberClient` — a deliberate, scoped exception to
the "hand-roll httpx, no SDK" convention used everywhere else in this codebase (see
decisions-log.md): pull/ack semantics (lease extension, at-least-once redelivery) are
real correctness risk if hand-rolled — a mishandled ack silently drops an email
notification.

`google.cloud.pubsub_v1.SubscriberClient` is a blocking, gRPC-backed client (no asyncio
variant used here), so every call is wrapped in `anyio.to_thread.run_sync` — same
pattern `init_embedding_model` already uses for its own blocking call.

`GOOGLE_PUBSUB_SUBSCRIPTION`/`GOOGLE_PUBSUB_TOPIC` (see core/config.py) are full resource
paths (`projects/<project>/subscriptions/<sub>`, `projects/<project>/topics/<topic>`) —
simpler than deriving the project id separately, and the pull worker needs the full path
either way. Authentication itself comes from `GOOGLE_APPLICATION_CREDENTIALS` via
standard Application Default Credentials, not from a settings field (see
GooglePubSubSettings' docstring).
"""

from typing import Any, TypedDict

import anyio
from google.cloud import pubsub_v1

from ..config import settings

_subscriber: pubsub_v1.SubscriberClient | None = None


class PulledMessage(TypedDict):
    ack_id: str
    data: bytes
    attributes: dict[str, str]


def _get_subscriber() -> pubsub_v1.SubscriberClient:
    global _subscriber
    if _subscriber is None:
        _subscriber = pubsub_v1.SubscriberClient()
    return _subscriber


async def pull_messages(max_messages: int = 20) -> list[PulledMessage]:
    subscriber = _get_subscriber()

    def _pull() -> Any:
        return subscriber.pull(
            request={"subscription": settings.GOOGLE_PUBSUB_SUBSCRIPTION, "max_messages": max_messages},
            timeout=10.0,
        )

    response = await anyio.to_thread.run_sync(_pull)
    return [
        PulledMessage(
            ack_id=received.ack_id,
            data=received.message.data,
            attributes=dict(received.message.attributes),
        )
        for received in response.received_messages
    ]


async def ack_messages(ack_ids: list[str]) -> None:
    if not ack_ids:
        return

    subscriber = _get_subscriber()

    def _ack() -> None:
        subscriber.acknowledge(request={"subscription": settings.GOOGLE_PUBSUB_SUBSCRIPTION, "ack_ids": ack_ids})

    await anyio.to_thread.run_sync(_ack)
