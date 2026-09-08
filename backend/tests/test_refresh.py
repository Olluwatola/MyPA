"""Unit tests for POST /api/v1/refresh (rotates the refresh token)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.app.api.v1.refresh import refresh_access_token
from src.app.core.exceptions.http_exceptions import UnauthorizedException
from src.app.schemas.token import TokenPayload


def _request_with_cookie(value: str | None):
    request = Mock()
    request.cookies = {"refresh_token": value} if value else {}
    return request


def _payload(sub: str) -> TokenPayload:
    return TokenPayload(sub=sub, jti="old-jti", exp=9999999999, type="refresh")


class TestRefresh:
    @pytest.mark.asyncio
    async def test_missing_cookie_rejected(self, mock_db):
        request = _request_with_cookie(None)
        response = Mock()

        with pytest.raises(UnauthorizedException, match="Refresh token missing."):
            await refresh_access_token(request, response, mock_db)

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, mock_db):
        request = _request_with_cookie("garbage")
        response = Mock()

        with patch("src.app.api.v1.refresh.verify_token", new=AsyncMock(return_value=None)):
            with pytest.raises(UnauthorizedException, match="Invalid refresh token."):
                await refresh_access_token(request, response, mock_db)

    @pytest.mark.asyncio
    async def test_success_rotates_token(self, mock_db, current_user_dict):
        request = _request_with_cookie("old.refresh.jwt")
        response = Mock()
        payload = _payload(str(current_user_dict["id"]))

        with patch("src.app.api.v1.refresh.verify_token", new=AsyncMock(return_value=payload)):
            with patch("src.app.api.v1.refresh.blacklist_token", new=AsyncMock()) as mock_blacklist:
                with patch(
                    "src.app.api.v1.refresh.create_access_token", new=AsyncMock(return_value=("new.access", "jti-a"))
                ):
                    with patch(
                        "src.app.api.v1.refresh.create_refresh_token",
                        new=AsyncMock(return_value=("new.refresh", "jti-r")),
                    ):
                        result = await refresh_access_token(request, response, mock_db)

        mock_blacklist.assert_called_once_with(payload, mock_db)
        assert result == {"access_token": "new.access", "token_type": "bearer"}
        response.set_cookie.assert_called_once()
        assert response.set_cookie.call_args.kwargs["value"] == "new.refresh"

    @pytest.mark.asyncio
    async def test_replayed_old_refresh_token_rejected(self, mock_db):
        """Once rotated, the old cookie is blacklisted — verify_token() must reject
        a replay of it on a subsequent call."""
        request = _request_with_cookie("old.refresh.jwt")
        response = Mock()

        # Simulates the post-rotation state: the old jti is now in the blacklist,
        # so verify_token() (which checks the blacklist) returns None.
        with patch("src.app.api.v1.refresh.verify_token", new=AsyncMock(return_value=None)):
            with pytest.raises(UnauthorizedException, match="Invalid refresh token."):
                await refresh_access_token(request, response, mock_db)
