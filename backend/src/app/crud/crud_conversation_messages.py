from fastcrud import FastCRUD

from ..models.conversation_message import ConversationMessage
from ..schemas.conversation_message import ConversationMessageCreate, ConversationMessageRead

# Append-only table — ConversationMessageCreate reused for Update/UpdateInternal/Delete
# generic slots too (same trick as crud_memory_extraction_records.py); rows are only ever
# created or hard-deleted in bulk by the retention cron.
CRUDConversationMessage = FastCRUD[
    ConversationMessage,
    ConversationMessageCreate,
    ConversationMessageCreate,
    ConversationMessageCreate,
    ConversationMessageCreate,
    ConversationMessageRead,
]
crud_conversation_messages = CRUDConversationMessage(ConversationMessage)
