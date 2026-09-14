from pydantic import BaseModel


class TelegramChat(BaseModel):
    id: int


class TelegramMessage(BaseModel):
    """Only the fields this app actually reads out of Telegram's `Message` object."""

    chat: TelegramChat
    text: str | None = None


class TelegramUpdate(BaseModel):
    """Shape of a Telegram Bot API `Update` payload — only `message` is handled this
    slice (`allowed_updates=["message"]` at `setWebhook` time); `callback_query`/
    `edited_message`/etc are never subscribed to, so they're not modeled here."""

    update_id: int
    message: TelegramMessage | None = None
