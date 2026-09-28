"""Unit tests for core/utils/etag.py (N-38)."""

from fastapi import Request, Response
from uuid6 import uuid7

from src.app.core.utils.etag import etag_for, not_modified_or_none, with_etag


def _request(if_none_match: str | None = None) -> Request:
    headers = [(b"if-none-match", if_none_match.encode())] if if_none_match else []
    return Request({"type": "http", "method": "GET", "path": "/api/v1/goals", "headers": headers})


class TestEtagFor:
    def test_is_weak_and_stable_for_the_same_payload(self):
        user_id = uuid7()
        payload = {"data": [{"id": uuid7(), "title": "Launch ClientPal"}], "total_count": 1}

        etag = etag_for(payload, user_id)

        assert etag.startswith('W/"') and etag.endswith('"')
        assert len(etag) == len('W/""') + 32
        assert etag_for(payload, user_id) == etag

    def test_changes_when_the_payload_changes(self):
        user_id = uuid7()
        assert etag_for({"title": "a"}, user_id) != etag_for({"title": "b"}, user_id)

    def test_differs_between_users_with_identical_data(self):
        empty = {"data": [], "total_count": 0}
        assert etag_for(empty, uuid7()) != etag_for(empty, uuid7())


class TestNotModifiedOrNone:
    def test_matching_if_none_match_gives_304_with_the_etag(self):
        etag = etag_for({"title": "a"}, uuid7())

        response = not_modified_or_none(_request(if_none_match=etag), etag)

        assert response is not None
        assert response.status_code == 304
        assert response.headers["ETag"] == etag
        assert response.body == b""

    def test_no_header_or_a_different_etag_gives_none(self):
        etag = etag_for({"title": "a"}, uuid7())

        assert not_modified_or_none(_request(), etag) is None
        assert not_modified_or_none(_request(if_none_match='W/"something-else"'), etag) is None

    def test_weak_comparison_ignores_the_w_prefix_and_reads_lists(self):
        etag = etag_for({"title": "a"}, uuid7())
        strong_form = etag.removeprefix("W/")

        assert not_modified_or_none(_request(if_none_match=strong_form), etag) is not None
        assert not_modified_or_none(_request(if_none_match=f'"other", {etag}'), etag) is not None


class TestWithEtag:
    def test_sets_the_header_and_returns_the_payload(self):
        user_id = uuid7()
        response = Response()

        result = with_etag(_request(), response, {"title": "a"}, user_id)

        assert result == {"title": "a"}
        assert response.headers["ETag"] == etag_for({"title": "a"}, user_id)

    def test_returns_304_when_the_browser_copy_is_current(self):
        user_id = uuid7()
        etag = etag_for({"title": "a"}, user_id)

        result = with_etag(_request(if_none_match=etag), Response(), {"title": "a"}, user_id)

        assert isinstance(result, Response) and result.status_code == 304
