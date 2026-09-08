from datetime import datetime

from pydantic import BaseModel


class TokenBlacklistBase(BaseModel):
    jti: str
    token_type: str
    expires_at: datetime


class TokenBlacklistRead(TokenBlacklistBase):
    pass


class TokenBlacklistCreate(TokenBlacklistBase):
    pass


class TokenBlacklistUpdate(TokenBlacklistBase):
    pass
