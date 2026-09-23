from pydantic import BaseModel


class TelegramChat(BaseModel):
    id: int


class TelegramMessage(BaseModel):
    """Only the fields this app actually reads out of Telegram's `Message` object."""

    chat: TelegramChat
    text: str | None = None


class TelegramCallbackQuery(BaseModel):
    """A quick-pick inline-keyboard button tap (see `core/telegram/client.py`'s
    `build_inline_keyboard`) — added for Feature 1.7's Notion clarification flow, whose
    quick-pick goal buttons need `allowed_updates=["message", "callback_query"]` at
    `setWebhook` time to actually be delivered."""

    id: str
    data: str | None = None
    message: TelegramMessage | None = None  # for chat.id


class TelegramUpdate(BaseModel):
    """Shape of a Telegram Bot API `Update` payload — `message` and `callback_query` are
    handled this slice (`allowed_updates=["message", "callback_query"]` at `setWebhook`
    time); `edited_message`/etc are never subscribed to, so they're not modeled here."""

    update_id: int
    message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None
