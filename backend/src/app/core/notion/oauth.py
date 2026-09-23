"""Notion OAuth — mirrors `core/oauth/google.py`'s shape. Verified against Notion's
public OAuth documentation (developers.notion.com): the authorize URL takes
`owner=user` (not a scope param — Notion has no scopes, access is governed entirely by
which pages the user shares during the flow), and the token exchange uses HTTP Basic
auth with `client_id:client_secret` — unlike Google's client_secret-in-body — because
Notion's `/v1/oauth/token` spec requires it.
"""

from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import settings

NOTION_AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token"


def build_notion_authorize_url(state: str, redirect_uri: str | None = None) -> str:
    params = {
        "client_id": settings.NOTION_CLIENT_ID,
        "redirect_uri": redirect_uri or settings.NOTION_INTEGRATIONS_REDIRECT_URI,
        "response_type": "code",
        "owner": "user",
        "state": state,
    }
    return f"{NOTION_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str, redirect_uri: str | None = None) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or settings.NOTION_INTEGRATIONS_REDIRECT_URI,
    }
    auth = (settings.NOTION_CLIENT_ID, settings.NOTION_CLIENT_SECRET.get_secret_value())
    async with httpx.AsyncClient() as client:
        response = await client.post(NOTION_TOKEN_URL, json=data, auth=auth)
        response.raise_for_status()
        tokens: dict[str, Any] = response.json()
        return tokens
