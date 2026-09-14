"""Unit tests for core/telegram/linking.py: token creation, atomic consume (GETDEL), the
t.me deep-link builder, and the TelegramLink upsert/conflict-resolution logic. Against the
existing mock_redis fixture in conftest.py."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.telegram.linking import (
    build_telegram_deep_link,
    consume_link_token,
    create_link_token,
    link_telegram_chat,
)

MODULE = "src.app.core.telegram.linking"


class TestCreateLinkToken:
    @pytest.mark.asyncio
    async def test_sets_token_with_ttl(self, mock_redis):
        user_id = uuid7()
        with patch(f"{MODULE}.cache.client", mock_redis):
            token = await create_link_token(user_id)

        assert isinstance(token, str) and len(token) > 0
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        assert args[0] == f"telegram_link_token:{token}"
        assert args[1] == str(user_id)
        assert kwargs["ex"] == 900


class TestConsumeLinkToken:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user_id_and_deletes_it(self, mock_redis):
        user_id = uuid7()
        mock_redis.getdel.return_value = str(user_id).encode()
        with patch(f"{MODULE}.cache.client", mock_redis):
            result = await consume_link_token("some-token")

        assert result == user_id
        mock_redis.getdel.assert_called_once_with("telegram_link_token:some-token")

    @pytest.mark.asyncio
    async def test_missing_token_returns_none(self, mock_redis):
        mock_redis.getdel.return_value = None
        with patch(f"{MODULE}.cache.client", mock_redis):
            result = await consume_link_token("nonexistent")

        assert result is None


class TestBuildTelegramDeepLink:
    def test_builds_start_deep_link(self):
        with patch(f"{MODULE}.settings.TELEGRAM_BOT_USERNAME", "mypa_bot"):
            assert build_telegram_deep_link("abc123") == "https://t.me/mypa_bot?start=abc123"


class TestLinkTelegramChat:
    @pytest.mark.asyncio
    async def test_brand_new_user_and_chat_creates(self, mock_db):
        user_id = uuid7()
        with patch(f"{MODULE}.crud_telegram_link") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            mock_crud.create = AsyncMock()

            await link_telegram_chat(mock_db, user_id, 42)

        mock_crud.create.assert_called_once()
        created = mock_crud.create.call_args.kwargs["object"]
        assert created.user_id == user_id
        assert created.telegram_chat_id == 42

    @pytest.mark.asyncio
    async def test_existing_user_relinking_own_chat_updates(self, mock_db):
        user_id = uuid7()
        existing = {"id": uuid7(), "user_id": user_id}
        with patch(f"{MODULE}.crud_telegram_link") as mock_crud:
            # First call (stale_by_chat lookup) finds nothing on the new chat_id; second
            # call (existing_by_user lookup) finds this user's own prior row.
            mock_crud.get = AsyncMock(side_effect=[None, existing])
            mock_crud.update = AsyncMock()

            await link_telegram_chat(mock_db, user_id, 99)

        mock_crud.update.assert_called_once()
        assert mock_crud.update.call_args.kwargs["id"] == existing["id"]
        assert mock_crud.update.call_args.kwargs["object"]["telegram_chat_id"] == 99

    @pytest.mark.asyncio
    async def test_chat_claimed_by_a_different_user_is_reassigned_without_crashing(self, mock_db):
        """Proves the fix: previously, re-linking user A to a chat already claimed by
        user B only cleared the stale row on the create path, not the update path — if A
        also already had their own row, the update would hit the DB's unique constraint
        on telegram_chat_id and raise an unhandled IntegrityError (500). Now the stale
        row is always cleared first, regardless of which branch fires next."""
        user_a = uuid7()
        stale_row_owned_by_user_b = {"id": uuid7(), "user_id": uuid7()}
        a_existing_row = {"id": uuid7(), "user_id": user_a}
        with patch(f"{MODULE}.crud_telegram_link") as mock_crud:
            mock_crud.get = AsyncMock(side_effect=[stale_row_owned_by_user_b, a_existing_row])
            mock_crud.db_delete = AsyncMock()
            mock_crud.update = AsyncMock()

            await link_telegram_chat(mock_db, user_a, 200)

        mock_crud.db_delete.assert_called_once_with(db=mock_db, id=stale_row_owned_by_user_b["id"])
        mock_crud.update.assert_called_once()
        assert mock_crud.update.call_args.kwargs["id"] == a_existing_row["id"]
        assert mock_crud.update.call_args.kwargs["object"]["telegram_chat_id"] == 200
