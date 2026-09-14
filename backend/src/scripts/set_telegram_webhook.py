"""One-off script — registers `settings.TELEGRAM_WEBHOOK_URL` with Telegram's Bot API via
`setWebhook`, once per environment. Not part of any request/job path.

Usage: `uv run python -m src.scripts.set_telegram_webhook`
"""

import asyncio
import logging

from ..app.core.config import settings
from ..app.core.telegram.client import telegram_set_webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    await telegram_set_webhook(
        webhook_url=settings.TELEGRAM_WEBHOOK_URL,
        secret_token=settings.TELEGRAM_WEBHOOK_SECRET.get_secret_value(),
    )
    logger.info(f"Telegram webhook set to {settings.TELEGRAM_WEBHOOK_URL}")


if __name__ == "__main__":
    asyncio.run(main())
