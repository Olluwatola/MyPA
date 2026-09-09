"""Maps a failed LLM provider HTTP response to the right exception type.

A non-2xx response from a provider isn't one failure mode — a bad API key, an exhausted
rate limit, a malformed request, and a provider outage are all different problems and
deserve different status codes, rather than every one of them collapsing into a single
generic 422 ("your request was malformed") regardless of what actually went wrong.
"""

import httpx

from ..exceptions.http_exceptions import (
    CustomException,
    RateLimitException,
    UnauthorizedException,
    UnprocessableEntityException,
)

BAD_GATEWAY = 502


def raise_for_llm_status(response: httpx.Response, provider_label: str) -> None:
    if response.status_code < 400:
        return

    detail = f"{provider_label} API error: {response.status_code} {response.text}"

    if response.status_code in (401, 403):
        raise UnauthorizedException(detail)
    if response.status_code == 429:
        raise RateLimitException(detail)
    if response.status_code >= 500:
        # The provider itself failed (outage/overload) — not our request's fault, and not
        # any of fastcrud's named exception types, so a plain 502 (bad gateway) is the
        # accurate status for "the upstream service we depend on failed".
        raise CustomException(status_code=BAD_GATEWAY, detail=detail)
    raise UnprocessableEntityException(detail)
