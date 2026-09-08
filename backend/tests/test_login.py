"""Unit tests for POST /api/v1/login."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.security import OAuth2PasswordRequestForm

from src.app.api.v1.login import login_for_access_token
from src.app.core.exceptions.http_exceptions import UnauthorizedException


def _form(username: str, password: str) -> OAuth2PasswordRequestForm:
    return OAuth2PasswordRequestForm(username=username, password=password, scope="")


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, mock_db, current_user_dict):
        response = Mock()
        form = _form(current_user_dict["email"], "correct-password")

        with patch("src.app.api.v1.login.authenticate_user", new=AsyncMock(return_value=current_user_dict)):
            with patch("src.app.api.v1.login.create_access_token", new=AsyncMock(return_value=("access.jwt", "jti-a"))):
                with patch(
                    "src.app.api.v1.login.create_refresh_token",
                    new=AsyncMock(return_value=("refresh.jwt", "jti-r")),
                ):
                    result = await login_for_access_token(response, form, mock_db)

        assert result == {"access_token": "access.jwt", "token_type": "bearer"}
        response.set_cookie.assert_called_once()
        assert response.set_cookie.call_args.kwargs["value"] == "refresh.jwt"
        assert response.set_cookie.call_args.kwargs["httponly"] is True

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, mock_db, current_user_dict):
        response = Mock()
        form = _form(current_user_dict["email"], "wrong-password")

        with patch("src.app.api.v1.login.authenticate_user", new=AsyncMock(return_value=None)):
            with pytest.raises(UnauthorizedException, match="Wrong email or password."):
                await login_for_access_token(response, form, mock_db)

    @pytest.mark.asyncio
    async def test_login_oauth_only_user_rejected(self, mock_db, oauth_user_dict):
        """A Google-only user (no hashed_password) attempting password login gets a
        plain 401 — authenticate_user() must never pass None into verify_password()."""
        response = Mock()
        form = _form(oauth_user_dict["email"], "any-password")

        # authenticate_user() itself is responsible for the None-password short-circuit;
        # here we assert the route surfaces that as 401 rather than crashing.
        with patch("src.app.api.v1.login.authenticate_user", new=AsyncMock(return_value=None)):
            with pytest.raises(UnauthorizedException, match="Wrong email or password."):
                await login_for_access_token(response, form, mock_db)
