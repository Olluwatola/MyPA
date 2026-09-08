from pydantic import BaseModel, EmailStr


class GoogleUserInfo(BaseModel):
    """Shape of Google's `/oauth2/v3/userinfo` response (only the fields we use)."""

    sub: str
    email: EmailStr
    email_verified: bool = False
    given_name: str | None = None
    family_name: str | None = None
    name: str | None = None
    picture: str | None = None
