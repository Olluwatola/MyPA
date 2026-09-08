"""Unit tests for the Google OAuth login/callback routes.

Google's own endpoints are mocked (never hit over the network) via patches on
core.oauth.google's functions as imported into the route module.
"""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.api.v1.oauth_google import google_callback, google_login
from src.app.core.exceptions.http_exceptions import UnauthorizedException
from src.app.schemas.google_oauth import GoogleUserInfo


def _userinfo(**overrides) -> GoogleUserInfo:
    defaults = {
        "sub": "google-sub-123",
        "email": "person@example.com",
        "email_verified": True,
        "given_name": "Person",
        "family_name": "Example",
        "name": "Person Example",
        "picture": None,
    }
    defaults.update(overrides)
    return GoogleUserInfo(**defaults)


class TestGoogleLogin:
    @pytest.mark.asyncio
    async def test_sets_state_cookie_and_redirects(self):
        response = await google_login()
        assert response.status_code == 307
        assert "oauth_state" in response.headers.get("set-cookie", "")


class TestGoogleCallback:
    @pytest.mark.asyncio
    async def test_state_mismatch_rejected(self, mock_db):
        with pytest.raises(UnauthorizedException, match="Invalid OAuth state."):
            await google_callback(code="abc", state="expected", db=mock_db, oauth_state="different")

    @pytest.mark.asyncio
    async def test_missing_state_cookie_rejected(self, mock_db):
        with pytest.raises(UnauthorizedException, match="Invalid OAuth state."):
            await google_callback(code="abc", state="expected", db=mock_db, oauth_state=None)

    @pytest.mark.asyncio
    async def test_unverified_email_rejected(self, mock_db):
        with patch(
            "src.app.api.v1.oauth_google.exchange_code_for_tokens",
            new=AsyncMock(return_value={"access_token": "g-access"}),
        ):
            with patch(
                "src.app.api.v1.oauth_google.fetch_google_userinfo",
                new=AsyncMock(return_value=_userinfo(email_verified=False)),
            ):
                with pytest.raises(UnauthorizedException, match="not verified"):
                    await google_callback(code="abc", state="s", db=mock_db, oauth_state="s")

    @pytest.mark.asyncio
    async def test_new_user_created(self, mock_db):
        created = {"id": uuid7(), "email": "person@example.com", "first_name": "Person", "last_name": "Example"}

        with patch(
            "src.app.api.v1.oauth_google.exchange_code_for_tokens",
            new=AsyncMock(return_value={"access_token": "g-access"}),
        ):
            with patch("src.app.api.v1.oauth_google.fetch_google_userinfo", new=AsyncMock(return_value=_userinfo())):
                with patch("src.app.api.v1.oauth_google.crud_users") as mock_crud:
                    # Not found by (oauth_provider, oauth_sub), not found by email either.
                    mock_crud.get = AsyncMock(side_effect=[None, None])
                    mock_crud.create = AsyncMock(return_value=created)
                    with patch(
                        "src.app.api.v1.oauth_google.create_refresh_token",
                        new=AsyncMock(return_value=("refresh.jwt", "jti-r")),
                    ):
                        redirect = await google_callback(code="abc", state="s", db=mock_db, oauth_state="s")

        mock_crud.create.assert_called_once()
        created_object = mock_crud.create.call_args.kwargs["object"]
        assert created_object.oauth_provider == "google"
        assert created_object.oauth_sub == "google-sub-123"
        assert created_object.hashed_password is None
        assert redirect.status_code == 307

    @pytest.mark.asyncio
    async def test_existing_oauth_user_reused(self, mock_db):
        existing = {"id": uuid7(), "email": "person@example.com", "first_name": "Person", "last_name": "Example"}

        with patch(
            "src.app.api.v1.oauth_google.exchange_code_for_tokens",
            new=AsyncMock(return_value={"access_token": "g-access"}),
        ):
            with patch("src.app.api.v1.oauth_google.fetch_google_userinfo", new=AsyncMock(return_value=_userinfo())):
                with patch("src.app.api.v1.oauth_google.crud_users") as mock_crud:
                    mock_crud.get = AsyncMock(return_value=existing)
                    mock_crud.create = AsyncMock()
                    with patch(
                        "src.app.api.v1.oauth_google.create_refresh_token",
                        new=AsyncMock(return_value=("refresh.jwt", "jti-r")),
                    ):
                        await google_callback(code="abc", state="s", db=mock_db, oauth_state="s")

        mock_crud.create.assert_not_called()
        mock_crud.get.assert_called_once_with(db=mock_db, oauth_provider="google", oauth_sub="google-sub-123")

    @pytest.mark.asyncio
    async def test_auto_link_by_email(self, mock_db):
        """A password account with a matching, Google-verified email gets the Google
        identity attached rather than a duplicate user created."""
        existing = {"id": uuid7(), "email": "person@example.com", "first_name": "Person", "last_name": "Example"}
        linked = {**existing, "oauth_provider": "google", "oauth_sub": "google-sub-123"}

        with patch(
            "src.app.api.v1.oauth_google.exchange_code_for_tokens",
            new=AsyncMock(return_value={"access_token": "g-access"}),
        ):
            with patch("src.app.api.v1.oauth_google.fetch_google_userinfo", new=AsyncMock(return_value=_userinfo())):
                with patch("src.app.api.v1.oauth_google.crud_users") as mock_crud:
                    # Not found by (oauth_provider, oauth_sub); found by email.
                    mock_crud.get = AsyncMock(side_effect=[None, existing, linked])
                    mock_crud.update = AsyncMock()
                    mock_crud.create = AsyncMock()
                    with patch(
                        "src.app.api.v1.oauth_google.create_refresh_token",
                        new=AsyncMock(return_value=("refresh.jwt", "jti-r")),
                    ):
                        await google_callback(code="abc", state="s", db=mock_db, oauth_state="s")

        mock_crud.create.assert_not_called()
        mock_crud.update.assert_called_once_with(
            db=mock_db, object={"oauth_provider": "google", "oauth_sub": "google-sub-123"}, id=existing["id"]
        )
