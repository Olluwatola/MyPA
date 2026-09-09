"""Shared retry helper, used by both provider adapters.

Retries two distinct failure modes the same way (same backoff, same attempt budget):
- HTTP 429 (rate limit) responses — deliberately excludes 500/502/503. A completion call
  is a non-idempotent, billable POST: a 429 means the request was rejected before taking
  effect (safe to retry), but a 500/502/503 is ambiguous (the provider may have already
  processed and billed it) — retrying risks a duplicate billed call. See decisions-log.md.
- Transport-level failures (`httpx.TransportError` — connection errors, timeouts): these
  never reached the provider at all, so retrying carries none of the double-billing risk
  above.
"""

from collections.abc import Awaitable, Callable

import anyio
import httpx

DEFAULT_RETRYABLE_STATUS_CODES = frozenset({429})
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_BACKOFF_MS = 250


async def execute_with_retry(
    fn: Callable[[], Awaitable[httpx.Response]],
    retryable_status_codes: set[int] | frozenset[int] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_backoff_ms: int = DEFAULT_BASE_BACKOFF_MS,
) -> httpx.Response:
    codes = retryable_status_codes if retryable_status_codes is not None else DEFAULT_RETRYABLE_STATUS_CODES

    last_response: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await fn()
        except httpx.TransportError:
            # Never reached the provider at all, so retrying carries none of the
            # double-billing risk a 500/502/503 does — re-raised once attempts run out.
            if attempt == max_retries:
                raise
            await anyio.sleep(base_backoff_ms / 1000 * 2**attempt)
            continue

        if response.status_code not in codes or attempt == max_retries:
            return response
        last_response = response
        await anyio.sleep(base_backoff_ms / 1000 * 2**attempt)
    return last_response  # type: ignore[return-value]
