"""Unit tests for user registration and the current-user endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

from src.app.api.v1.users import read_current_user, write_user
from src.app.core.exceptions.http_exceptions import DuplicateValueException
from src.app.schemas.user import UserCreate


class TestWriteUser:
    """POST /api/v1/register"""

    @pytest.mark.asyncio
    async def test_create_user_success(self, mock_db, sample_user_data, sample_user_read):
        user_create = UserCreate(**sample_user_data)

        with patch("src.app.api.v1.users.crud_users") as mock_crud:
            mock_crud.exists = AsyncMock(return_value=False)
            mock_crud.create = AsyncMock(return_value=sample_user_read.model_dump())

            with patch("src.app.api.v1.users.get_password_hash") as mock_hash:
                mock_hash.return_value = "hashed_password"

                result = await write_user(user_create, mock_db)

                assert result == sample_user_read.model_dump()
                mock_crud.exists.assert_called_once_with(db=mock_db, email=user_create.email)
                mock_crud.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_user_duplicate_email(self, mock_db, sample_user_data):
        user_create = UserCreate(**sample_user_data)

        with patch("src.app.api.v1.users.crud_users") as mock_crud:
            mock_crud.exists = AsyncMock(return_value=True)

            with pytest.raises(DuplicateValueException, match="Email is already registered"):
                await write_user(user_create, mock_db)


class TestReadCurrentUser:
    """GET /api/v1/users/me"""

    @pytest.mark.asyncio
    async def test_read_current_user(self, current_user_dict):
        result = await read_current_user(current_user_dict)
        assert result == current_user_dict
