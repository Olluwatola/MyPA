"""Unit tests for POST /api/v1/logout."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.app.api.v1.logout import logout_user
from src.app.schemas.token import TokenPayload


def _payload(token_type: str) -> TokenPayload:
    return TokenPayload(sub="user-id", jti=f"{token_type}-jti", exp=9999999999, type=token_type)


class TestLogout:
    @pytest.mark.asyncio
    async def test_blacklists_both_tokens(self, mock_db):
        response = Mock()
        access_payload = _payload("access")
        refresh_payload = _payload("refresh")

        def fake_decode(token: str):
            return access_payload if token == "access.jwt" else refresh_payload

        with patch("src.app.api.v1.logout.decode_token_ignoring_expiry", side_effect=fake_decode):
            with patch("src.app.api.v1.logout.blacklist_token", new=AsyncMock()) as mock_blacklist:
                await logout_user(response, "access.jwt", mock_db, refresh_token="refresh.jwt")

        assert mock_blacklist.call_count == 2
        mock_blacklist.assert_any_call(access_payload, mock_db)
        mock_blacklist.assert_any_call(refresh_payload, mock_db)
        response.delete_cookie.assert_called_once_with(key="refresh_token", path="/api/v1")

    @pytest.mark.asyncio
    async def test_no_refresh_cookie_still_logs_out(self, mock_db):
        response = Mock()
        access_payload = _payload("access")

        with patch("src.app.api.v1.logout.decode_token_ignoring_expiry", return_value=access_payload):
            with patch("src.app.api.v1.logout.blacklist_token", new=AsyncMock()) as mock_blacklist:
                await logout_user(response, "access.jwt", mock_db, refresh_token=None)

        mock_blacklist.assert_called_once_with(access_payload, mock_db)

    @pytest.mark.asyncio
    async def test_undecodable_access_token_does_not_crash(self, mock_db):
        response = Mock()

        with patch("src.app.api.v1.logout.decode_token_ignoring_expiry", return_value=None):
            with patch("src.app.api.v1.logout.blacklist_token", new=AsyncMock()) as mock_blacklist:
                await logout_user(response, "garbage", mock_db, refresh_token=None)

        mock_blacklist.assert_not_called()
        response.delete_cookie.assert_called_once()
