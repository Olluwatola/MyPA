from typing import Any
from urllib.parse import urlencode

import httpx

from ...schemas.google_oauth import GoogleUserInfo
from ..config import settings
from ..logger import logging

logger = logging.getLogger(__name__)

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def build_google_authorize_url(
    state: str,
    scope: str = "openid email profile",
    access_type: str = "online",
    prompt: str = "select_account",
    redirect_uri: str | None = None,
) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri or settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "access_type": access_type,
        "prompt": prompt,
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str, redirect_uri: str | None = None) -> dict[str, Any]:
    data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
        "redirect_uri": redirect_uri or settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)
        response.raise_for_status()
        tokens: dict[str, Any] = response.json()
        return tokens


async def fetch_google_userinfo(google_access_token: str) -> GoogleUserInfo:
    headers = {"Authorization": f"Bearer {google_access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(GOOGLE_USERINFO_URL, headers=headers)
        response.raise_for_status()
        return GoogleUserInfo(**response.json())


async def refresh_google_access_token(refresh_token: str) -> dict[str, Any]:
    """Used by `core/integrations/token_refresh.py` to keep a connection's access token
    valid without re-running the whole consent flow."""
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)
        response.raise_for_status()
        tokens: dict[str, Any] = response.json()
        return tokens


async def revoke_google_token(access_token: str) -> None:
    """Used only when disconnecting the *last* remaining sibling connection (see
    api/v1/integrations_google.py) — revoking with Google invalidates the shared
    email+calendar token pair, so it must never be called while a sibling type is still
    connected."""
    async with httpx.AsyncClient() as client:
        response = await client.post(GOOGLE_REVOKE_URL, params={"token": access_token})
        response.raise_for_status()
