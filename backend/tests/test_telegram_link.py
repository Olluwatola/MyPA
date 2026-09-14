"""Unit tests for the Telegram linking-flow endpoints: GET /telegram/link (deep-link
mint) and DELETE /telegram/link (unlink). Mirrors test_integrations_google.py's
connect/disconnect shape."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.api.v1.telegram_link import erase_telegram_link, read_telegram_link_url
from src.app.core.exceptions.http_exceptions import NotFoundException

MODULE = "src.app.api.v1.telegram_link"


class TestReadTelegramLinkUrl:
    @pytest.mark.asyncio
    async def test_returns_deep_link_url(self, current_user_dict):
        with (
            patch(f"{MODULE}.create_link_token", new=AsyncMock(return_value="the-token")),
            patch(f"{MODULE}.build_telegram_deep_link", return_value="https://t.me/mypa_bot?start=the-token"),
        ):
            result = await read_telegram_link_url(current_user=current_user_dict)

        assert result.deep_link_url == "https://t.me/mypa_bot?start=the-token"


class TestEraseTelegramLink:
    @pytest.mark.asyncio
    async def test_deletes_existing_link(self, current_user_dict, mock_db):
        link = {"id": uuid7()}
        with patch(f"{MODULE}.crud_telegram_link") as mock_crud:
            mock_crud.get = AsyncMock(return_value=link)
            mock_crud.db_delete = AsyncMock()

            result = await erase_telegram_link(current_user=current_user_dict, db=mock_db)

        mock_crud.db_delete.assert_called_once_with(db=mock_db, id=link["id"])
        assert result.status == "unlinked"

    @pytest.mark.asyncio
    async def test_raises_not_found_when_no_link(self, current_user_dict, mock_db):
        with patch(f"{MODULE}.crud_telegram_link") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)

            with pytest.raises(NotFoundException):
                await erase_telegram_link(current_user=current_user_dict, db=mock_db)
