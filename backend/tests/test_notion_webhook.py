"""Unit tests for the Notion webhook receiver: verification handshake, valid/invalid
signature, page.created vs page.content_updated routing, and malformed-payload no-op.
Mirrors test_calendar_webhook.py/test_telegram_webhook.py's shape."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import SecretStr

from src.app.api.v1.webhooks_notion import notion_webhook

MODULE = "src.app.api.v1.webhooks_notion"
VERIFICATION_TOKEN = "secret_the-verification-token"


def _request(payload: dict, signed: bool = True) -> Mock:
    body = json.dumps(payload).encode()
    request = Mock()
    request.body = AsyncMock(return_value=body)
    headers = {}
    if signed:
        signature = "sha256=" + hmac.new(VERIFICATION_TOKEN.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Notion-Signature"] = signature
    request.headers = headers
    return request


class TestVerificationHandshake:
    @pytest.mark.asyncio
    async def test_verification_token_payload_is_accepted_unsigned(self):
        request = _request({"verification_token": VERIFICATION_TOKEN}, signed=False)
        with patch(f"{MODULE}.settings.NOTION_WEBHOOK_VERIFICATION_TOKEN", SecretStr(VERIFICATION_TOKEN)):
            response = await notion_webhook(request)
        assert response.status_code == 200


class TestSignatureValidation:
    @pytest.mark.asyncio
    async def test_missing_signature_rejected(self):
        from src.app.core.exceptions.http_exceptions import UnauthorizedException

        request = _request({"type": "page.created", "entity": {"id": "page-1"}}, signed=False)
        with patch(f"{MODULE}.settings.NOTION_WEBHOOK_VERIFICATION_TOKEN", SecretStr(VERIFICATION_TOKEN)):
            with pytest.raises(UnauthorizedException):
                await notion_webhook(request)

    @pytest.mark.asyncio
    async def test_wrong_signature_rejected(self):
        from src.app.core.exceptions.http_exceptions import UnauthorizedException

        request = _request({"type": "page.created", "entity": {"id": "page-1"}})
        request.headers["X-Notion-Signature"] = "sha256=wrong"
        with patch(f"{MODULE}.settings.NOTION_WEBHOOK_VERIFICATION_TOKEN", SecretStr(VERIFICATION_TOKEN)):
            with pytest.raises(UnauthorizedException):
                await notion_webhook(request)


class TestMalformedPayload:
    @pytest.mark.asyncio
    async def test_non_json_body_is_a_no_op(self):
        request = Mock()
        request.body = AsyncMock(return_value=b"not json")
        response = await notion_webhook(request)
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_missing_entity_id_is_a_no_op(self):
        request = _request({"type": "page.created", "entity": {}})
        with (
            patch(f"{MODULE}.settings.NOTION_WEBHOOK_VERIFICATION_TOKEN", SecretStr(VERIFICATION_TOKEN)),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_queue.pool.enqueue_job = AsyncMock()
            response = await notion_webhook(request)
        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_not_called()


class TestEventRouting:
    @pytest.mark.asyncio
    async def test_page_created_enqueues_initial_extraction(self):
        request = _request({"type": "page.created", "entity": {"id": "page-1"}})
        with (
            patch(f"{MODULE}.settings.NOTION_WEBHOOK_VERIFICATION_TOKEN", SecretStr(VERIFICATION_TOKEN)),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_queue.pool.enqueue_job = AsyncMock()
            response = await notion_webhook(request)

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_called_once_with(
            "run_notion_initial_extraction", "page-1", _job_id="notion-created-page-1"
        )

    @pytest.mark.asyncio
    async def test_page_content_updated_enqueues_edit_processing_with_block_ids(self):
        payload = {
            "id": "event-1",
            "type": "page.content_updated",
            "entity": {"id": "page-1"},
            "data": {"updated_blocks": [{"id": "block-a"}, {"id": "block-b"}]},
        }
        request = _request(payload)
        with (
            patch(f"{MODULE}.settings.NOTION_WEBHOOK_VERIFICATION_TOKEN", SecretStr(VERIFICATION_TOKEN)),
            patch(f"{MODULE}.queue") as mock_queue,
        ):
            mock_queue.pool.enqueue_job = AsyncMock()
            response = await notion_webhook(request)

        assert response.status_code == 204
        mock_queue.pool.enqueue_job.assert_called_once_with(
            "process_notion_content_updated",
            "page-1",
            ["block-a", "block-b"],
            _job_id="notion-updated-page-1-event-1",
        )
