from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenPayload(BaseModel):
    """Decoded JWT claims — `sub` is the user's `id` (UUID, as a string)."""

    sub: str
    jti: str
    exp: int
    type: str
