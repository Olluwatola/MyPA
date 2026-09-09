"""Direct unit tests of execute_with_retry's backoff/retry-count logic.

Relocated with the module in Feature 1.4 (core/llm/retry.py -> core/utils/http_retry.py)
— import path only, no behavior change."""

from unittest.mock import Mock

import httpx
import pytest

from src.app.core.utils.http_retry import DEFAULT_RETRYABLE_STATUS_CODES, execute_with_retry


def make_response(status_code: int) -> Mock:
    response = Mock()
    response.status_code = status_code
    return response


class TestExecuteWithRetry:
    @pytest.mark.asyncio
    async def test_success_on_first_try_not_retried(self):
        response = make_response(200)
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            return response

        result = await execute_with_retry(fn, base_backoff_ms=1)

        assert result is response
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self):
        responses = [make_response(429), make_response(200)]

        async def fn():
            return responses.pop(0)

        result = await execute_with_retry(fn, base_backoff_ms=1)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_non_retryable_status_is_not_retried(self):
        response = make_response(500)
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            return response

        result = await execute_with_retry(fn, base_backoff_ms=1)

        assert result is response
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_max_retries_and_returns_last_response(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            return make_response(429)

        result = await execute_with_retry(fn, max_retries=2, base_backoff_ms=1)

        assert result.status_code == 429
        assert call_count == 3  # initial attempt + 2 retries

    @pytest.mark.asyncio
    async def test_transport_error_is_retried_then_succeeds(self):
        """A ConnectError/ReadTimeout never reached the provider at all, so retrying it
        carries none of the double-billing risk a 500/502/503 response does."""
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("connection refused")
            return make_response(200)

        result = await execute_with_retry(fn, base_backoff_ms=1)

        assert result.status_code == 200
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_transport_error_exhausting_retries_reraises(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("timed out")

        with pytest.raises(httpx.ReadTimeout):
            await execute_with_retry(fn, max_retries=2, base_backoff_ms=1)

        assert call_count == 3  # initial attempt + 2 retries

    def test_default_retryable_status_codes_is_immutable(self):
        """Guards against the classic mutable-default-argument footgun — the shared
        default must not be a plain (mutable) set."""
        assert isinstance(DEFAULT_RETRYABLE_STATUS_CODES, frozenset)

    @pytest.mark.asyncio
    async def test_custom_retryable_status_codes_are_respected(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            return make_response(503)

        result = await execute_with_retry(fn, retryable_status_codes={503}, max_retries=1, base_backoff_ms=1)

        assert result.status_code == 503
        assert call_count == 2  # 503 is retried only because it was explicitly opted in
