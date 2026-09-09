"""ARQ worker entry point: `uv run arq src.app.core.worker.WorkerSettings`.

The worker is a separate process from the FastAPI app — `on_startup` re-initializes the
LLM tiers + embedding model exactly like `core/setup.py`'s lifespan does at API startup,
since neither carries over from the API process.
"""

from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

from .config import settings
from .integrations.jobs import (
    process_calendar_webhook,
    process_gmail_notification,
    pull_gmail_pubsub_notifications,
    renew_watches_before_expiry,
)
from .llm.embedding_model import init_embedding_model
from .setup import build_llm_service


async def on_startup(ctx: dict[str, Any]) -> None:
    build_llm_service()
    await init_embedding_model()


class WorkerSettings:
    functions = [process_gmail_notification, process_calendar_webhook]
    cron_jobs = [
        cron(pull_gmail_pubsub_notifications, second={0, 15, 30, 45}),  # every 15s
        cron(renew_watches_before_expiry, minute=0),  # hourly
    ]
    on_startup = on_startup
    redis_settings = RedisSettings(host=settings.REDIS_QUEUE_HOST, port=settings.REDIS_QUEUE_PORT)
