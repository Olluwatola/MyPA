"""Weak ETags for GET routes (N-38).

`/api/` responses carry `Cache-Control: private, no-cache` (ClientCacheMiddleware), so the browser
keeps the last reply, sends `If-None-Match` by itself on the next request, and turns a `304` back
into a normal `200` for the page. Only the routes that call these helpers get ETags — a middleware
would have to buffer every response, including future streams.
"""

import hashlib
import json
from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder


def etag_for(payload: Any, user_id: Any) -> str:
    """Weak ETag over the JSON-encoded payload plus the user's id.

    The user id is part of the hash so two users with identical data (e.g. both with an empty list)
    never share a cached reply after a logout/login in the same browser.

    Parameters
    ----------
    payload: Any
        The response body, as the route would return it.
    user_id: Any
        The current user's id.

    Returns
    -------
    str
        `W/"<32 hex chars>"`.
    """
    encoded = json.dumps(jsonable_encoder(payload), sort_keys=True) + str(user_id)
    return f'W/"{hashlib.sha256(encoded.encode()).hexdigest()[:32]}"'


def not_modified_or_none(request: Request, etag: str) -> Response | None:
    """A `304` carrying the same ETag if `If-None-Match` matches it, else `None`.

    Parameters
    ----------
    request: Request
        The incoming request.
    etag: str
        The ETag of the response the route is about to send.

    Returns
    -------
    Response | None
        The `304` to return instead of the body, or `None` to send the body as usual.
    """
    # If-None-Match uses weak comparison (RFC 9110 §13.1.2): the W/ prefix is ignored.
    candidates = {tag.strip().removeprefix("W/") for tag in request.headers.get("if-none-match", "").split(",")}
    if etag.removeprefix("W/") in candidates or "*" in candidates:
        return Response(status_code=304, headers={"ETag": etag})
    return None


def with_etag(request: Request, response: Response, payload: dict, user_id: Any) -> dict | Response:
    """The payload with an `ETag` header set, or a bodyless `304` if the browser's copy is current.

    Parameters
    ----------
    request: Request
        The incoming request.
    response: Response
        The route's response, to carry the `ETag` header.
    payload: dict
        The body the route would return.
    user_id: Any
        The current user's id.

    Returns
    -------
    dict | Response
        The payload, or the `304` to return instead.
    """
    etag = etag_for(payload, user_id)
    not_modified = not_modified_or_none(request, etag)
    if not_modified is not None:
        return not_modified
    response.headers["ETag"] = etag
    return payload
