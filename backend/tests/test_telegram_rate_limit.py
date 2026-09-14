"""Unit tests for core/telegram/rate_limit.py: fixed-window counter behavior. Against
the existing mock_redis fixture in conftest.py."""

from unittest.mock import patch

import pytest

from src.app.core.telegram.rate_limit import is_rate_limited

MODULE = "src.app.core.telegram.rate_limit"


class TestIsRateLimited:
    @pytest.mark.asyncio
    async def test_first_message_sets_window_expiry(self, mock_redis):
        mock_redis.incr.return_value = 1
        with patch(f"{MODULE}.cache.client", mock_redis):
            limited = await is_rate_limited(42)

        assert limited is False
        mock_redis.expire.assert_called_once_with("telegram_rate_limit:42", 60)

    @pytest.mark.asyncio
    async def test_subsequent_message_does_not_reset_expiry(self, mock_redis):
        mock_redis.incr.return_value = 2
        with patch(f"{MODULE}.cache.client", mock_redis):
            limited = await is_rate_limited(42)

        assert limited is False
        mock_redis.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_over_limit_returns_true(self, mock_redis):
        mock_redis.incr.return_value = 11
        with patch(f"{MODULE}.cache.client", mock_redis):
            limited = await is_rate_limited(42)

        assert limited is True

    @pytest.mark.asyncio
    async def test_at_limit_is_not_yet_limited(self, mock_redis):
        mock_redis.incr.return_value = 10
        with patch(f"{MODULE}.cache.client", mock_redis):
            limited = await is_rate_limited(42)

        assert limited is False
