"""Direct unit tests of core/oauth/google.py: the Feature 1.4 parametrization
(backward-compatible defaults for the existing login call sites) plus the two new
refresh/revoke functions. Google's endpoints are mocked via httpx.AsyncClient patches,
never hit over the network."""

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from src.app.core.oauth.google import (
    build_google_authorize_url,
    exchange_code_for_tokens,
    refresh_google_access_token,
    revoke_google_token,
)


def make_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    # `request=` is required for `.raise_for_status()` to work on a manually-constructed
    # Response — a real httpx send cycle sets it automatically, a mocked one doesn't.
    return httpx.Response(
        status_code=status_code, json=json_body or {}, request=httpx.Request("POST", "https://example.com")
    )


class TestBuildGoogleAuthorizeUrl:
    def test_defaults_match_login_flow(self):
        """No new arguments passed — the existing login call site's behavior must be
        unchanged by the parametrization."""
        url = build_google_authorize_url("state-123")
        params = parse_qs(urlparse(url).query)

        assert params["scope"] == ["openid email profile"]
        assert params["access_type"] == ["online"]
        assert params["prompt"] == ["select_account"]
        assert params["state"] == ["state-123"]
        assert "redirect_uri" in params

    def test_custom_params_override_defaults(self):
        url = build_google_authorize_url(
            "state-123",
            scope="a b",
            access_type="offline",
            prompt="consent",
            redirect_uri="https://example.com/callback",
        )
        params = parse_qs(urlparse(url).query)

        assert params["scope"] == ["a b"]
        assert params["access_type"] == ["offline"]
        assert params["prompt"] == ["consent"]
        assert params["redirect_uri"] == ["https://example.com/callback"]


class TestExchangeCodeForTokens:
    @pytest.mark.asyncio
    async def test_defaults_to_settings_redirect_uri(self):
        mock_post = AsyncMock(return_value=make_response(200, {"access_token": "g-access"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            await exchange_code_for_tokens("code-abc")

        sent_data = mock_post.call_args.kwargs["data"]
        assert "redirect_uri" in sent_data

    @pytest.mark.asyncio
    async def test_custom_redirect_uri_is_used(self):
        """Correction #2 from the plan: exchange_code_for_tokens also hardcoded
        redirect_uri — a second redirect URI must actually be honored here too, or the
        token exchange fails with redirect_uri_mismatch."""
        mock_post = AsyncMock(return_value=make_response(200, {"access_token": "g-access"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            await exchange_code_for_tokens("code-abc", redirect_uri="https://example.com/integrations/callback")

        sent_data = mock_post.call_args.kwargs["data"]
        assert sent_data["redirect_uri"] == "https://example.com/integrations/callback"


class TestRefreshGoogleAccessToken:
    @pytest.mark.asyncio
    async def test_sends_refresh_grant(self):
        mock_post = AsyncMock(return_value=make_response(200, {"access_token": "new-access", "expires_in": 3600}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            tokens = await refresh_google_access_token("stored-refresh-token")

        assert tokens["access_token"] == "new-access"
        sent_data = mock_post.call_args.kwargs["data"]
        assert sent_data["grant_type"] == "refresh_token"
        assert sent_data["refresh_token"] == "stored-refresh-token"

    @pytest.mark.asyncio
    async def test_error_response_raises(self):
        mock_post = AsyncMock(return_value=make_response(400, {"error": "invalid_grant"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await refresh_google_access_token("revoked-refresh-token")


class TestRevokeGoogleToken:
    @pytest.mark.asyncio
    async def test_sends_token_to_revoke_endpoint(self):
        mock_post = AsyncMock(return_value=make_response(200))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            await revoke_google_token("some-access-token")

        assert mock_post.call_args.kwargs["params"]["token"] == "some-access-token"

    @pytest.mark.asyncio
    async def test_error_response_raises(self):
        mock_post = AsyncMock(return_value=make_response(400))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await revoke_google_token("already-invalid-token")
