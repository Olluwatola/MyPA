"""ARQ worker entry point: `uv run arq src.app.core.worker.WorkerSettings`.

The worker is a separate process from the FastAPI app — `on_startup` re-initializes the
LLM tiers + embedding model exactly like `core/setup.py`'s lifespan does at API startup,
since neither carries over from the API process.
"""

from typing import Any

from arq import func
from arq.connections import RedisSettings
from arq.cron import cron

from .config import settings
from .integrations.jobs import (
    ONBOARDING_JOB_TIMEOUT_SECONDS,
    ONBOARDING_MAX_TRIES,
    process_calendar_webhook,
    process_gmail_notification,
    pull_gmail_pubsub_notifications,
    renew_watches_before_expiry,
    run_onboarding_ingestion,
)
from .llm.embedding_model import init_embedding_model
from .setup import build_llm_service


async def on_startup(ctx: dict[str, Any]) -> None:
    build_llm_service()
    await init_embedding_model()


class WorkerSettings:
    # max_tries wraps every non-cron job for real ARQ-level retry (a plain uncaught
    # exception in a job function is NOT retried by ARQ's own default — only a job that
    # raises arq.Retry is; see jobs.py's own docstrings). Cron jobs (below) don't need
    # this — arq.cron() reschedules purely from wall-clock, so a failed tick is already
    # "retried" for free by the next one. process_calendar_webhook and
    # run_onboarding_ingestion also get a raised `timeout` — both re-list a full
    # multi-item window (not just a delta), so their worst-case single-attempt runtime can
    # exceed ARQ's 300s default, especially on a user's first-ever pass with no
    # `ingestion_sync` rows yet to skip.
    functions = [
        func(process_gmail_notification, max_tries=5),
        func(process_calendar_webhook, max_tries=5, timeout=600),
        func(run_onboarding_ingestion, max_tries=ONBOARDING_MAX_TRIES, timeout=ONBOARDING_JOB_TIMEOUT_SECONDS),
    ]
    cron_jobs = [
        cron(pull_gmail_pubsub_notifications, second={0, 15, 30, 45}),  # every 15s
        cron(renew_watches_before_expiry, minute=0),  # hourly
    ]
    on_startup = on_startup
    redis_settings = RedisSettings(host=settings.REDIS_QUEUE_HOST, port=settings.REDIS_QUEUE_PORT)
