"""Unit tests for the JWT/blacklist choke point in src.app.core.security."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.security import (
    TokenType,
    authenticate_user,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_token,
)
from src.app.schemas.token import TokenPayload


class TestAuthenticateUser:
    @pytest.mark.asyncio
    async def test_user_not_found(self, mock_db):
        with patch("src.app.core.security.crud_users") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            result = await authenticate_user(email="nobody@example.com", password="x", db=mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_oauth_only_user_never_hits_verify_password(self, mock_db, oauth_user_dict):
        """hashed_password is None for a Google-only user — must short-circuit to
        None rather than passing None into verify_password()."""
        with patch("src.app.core.security.crud_users") as mock_crud:
            mock_crud.get = AsyncMock(return_value=oauth_user_dict)
            with patch("src.app.core.security.verify_password") as mock_verify:
                result = await authenticate_user(email=oauth_user_dict["email"], password="x", db=mock_db)
                mock_verify.assert_not_called()
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_password(self, mock_db, current_user_dict):
        with patch("src.app.core.security.crud_users") as mock_crud:
            mock_crud.get = AsyncMock(return_value=current_user_dict)
            with patch("src.app.core.security.verify_password", new=AsyncMock(return_value=False)):
                result = await authenticate_user(email=current_user_dict["email"], password="wrong", db=mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_success(self, mock_db, current_user_dict):
        with patch("src.app.core.security.crud_users") as mock_crud:
            mock_crud.get = AsyncMock(return_value=current_user_dict)
            with patch("src.app.core.security.verify_password", new=AsyncMock(return_value=True)):
                result = await authenticate_user(email=current_user_dict["email"], password="right", db=mock_db)
        assert result == current_user_dict


class TestTokenRoundTrip:
    @pytest.mark.asyncio
    async def test_create_and_verify_access_token(self, mock_db, current_user_dict):
        token, jti = await create_access_token(user_id=current_user_dict["id"])

        with patch("src.app.core.security.crud_token_blacklist") as mock_crud:
            mock_crud.exists = AsyncMock(return_value=False)
            payload = await verify_token(token, TokenType.ACCESS, mock_db)

        assert payload is not None
        assert payload.jti == jti
        assert payload.type == TokenType.ACCESS.value
        assert payload.sub == str(current_user_dict["id"])

    @pytest.mark.asyncio
    async def test_wrong_token_type_rejected(self, mock_db, current_user_dict):
        token, _ = await create_refresh_token(user_id=current_user_dict["id"])

        with patch("src.app.core.security.crud_token_blacklist") as mock_crud:
            mock_crud.exists = AsyncMock(return_value=False)
            payload = await verify_token(token, TokenType.ACCESS, mock_db)

        assert payload is None

    @pytest.mark.asyncio
    async def test_blacklisted_token_rejected(self, mock_db, current_user_dict):
        token, jti = await create_access_token(user_id=current_user_dict["id"])

        with patch("src.app.core.security.crud_token_blacklist") as mock_crud:
            mock_crud.exists = AsyncMock(return_value=True)
            payload = await verify_token(token, TokenType.ACCESS, mock_db)

        assert payload is None

    @pytest.mark.asyncio
    async def test_blacklist_token_is_idempotent(self, mock_db):
        payload = TokenPayload(
            sub="00000000-0000-0000-0000-000000000000",
            jti="some-jti",
            exp=int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            type=TokenType.ACCESS.value,
        )

        with patch("src.app.core.security.crud_token_blacklist") as mock_crud:
            mock_crud.exists = AsyncMock(return_value=True)
            mock_crud.create = AsyncMock()
            await blacklist_token(payload, mock_db)
            mock_crud.create.assert_not_called()


def test_password_hash_roundtrip():
    hashed = get_password_hash("correct horse battery staple")
    assert hashed != "correct horse battery staple"
