"""Unit tests for the Notion OAuth connect/callback/disconnect flow — mirrors
test_integrations_google.py's shape: state-cookie CSRF, refresh_token-cookie user
recovery, upsert-not-duplicate, disconnect."""

from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.api.v1.integrations_notion import (
    STATE_COOKIE,
    connect_notion_integration,
    disconnect_notion_integration,
    notion_integrations_callback,
)
from src.app.core.exceptions.http_exceptions import NotFoundException, UnauthorizedException

MODULE = "src.app.api.v1.integrations_notion"


class TestConnect:
    @pytest.mark.asyncio
    async def test_sets_state_cookie_and_redirects_to_notion(self, current_user_dict):
        response = await connect_notion_integration(current_user=current_user_dict)
        assert response.status_code == 307
        assert STATE_COOKIE in response.headers.get("set-cookie", "")


class TestCallback:
    @pytest.mark.asyncio
    async def test_missing_state_cookie_rejected(self, mock_db):
        with pytest.raises(UnauthorizedException):
            await notion_integrations_callback(
                code="abc", state="xyz", db=mock_db, oauth_state=None, refresh_token_cookie="rt"
            )

    @pytest.mark.asyncio
    async def test_mismatched_state_rejected(self, mock_db):
        with pytest.raises(UnauthorizedException):
            await notion_integrations_callback(
                code="abc", state="xyz", db=mock_db, oauth_state="different", refresh_token_cookie="rt"
            )

    @pytest.mark.asyncio
    async def test_missing_refresh_token_cookie_rejected(self, mock_db):
        with pytest.raises(UnauthorizedException):
            await notion_integrations_callback(
                code="abc", state="xyz", db=mock_db, oauth_state="xyz", refresh_token_cookie=None
            )

    @pytest.mark.asyncio
    async def test_valid_callback_upserts_connection_and_syncs_pages(self, mock_db):
        user_id = uuid7()
        token_payload = type("Payload", (), {"sub": str(user_id)})()

        with (
            patch(f"{MODULE}.verify_token", new=AsyncMock(return_value=token_payload)),
            patch(
                f"{MODULE}.exchange_code_for_tokens",
                new=AsyncMock(return_value={"access_token": "notion-token", "workspace_name": "Acme"}),
            ),
            patch(f"{MODULE}.encrypt_token", return_value="encrypted"),
            patch(f"{MODULE}.crud_notion_connection") as mock_conn_crud,
            patch(f"{MODULE}.search_accessible_pages", new=AsyncMock(return_value=[])),
        ):
            mock_conn_crud.get = AsyncMock(return_value=None)
            mock_conn_crud.create = AsyncMock()

            response = await notion_integrations_callback(
                code="abc", state="xyz", db=mock_db, oauth_state="xyz", refresh_token_cookie="rt"
            )

        assert response.status_code == 307
        mock_conn_crud.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_upserts_existing_row_not_a_duplicate(self, mock_db):
        user_id = uuid7()
        token_payload = type("Payload", (), {"sub": str(user_id)})()
        existing = {"id": uuid7()}

        with (
            patch(f"{MODULE}.verify_token", new=AsyncMock(return_value=token_payload)),
            patch(
                f"{MODULE}.exchange_code_for_tokens",
                new=AsyncMock(return_value={"access_token": "notion-token", "workspace_name": "Acme"}),
            ),
            patch(f"{MODULE}.encrypt_token", return_value="encrypted"),
            patch(f"{MODULE}.crud_notion_connection") as mock_conn_crud,
            patch(f"{MODULE}.search_accessible_pages", new=AsyncMock(return_value=[])),
        ):
            mock_conn_crud.get = AsyncMock(return_value=existing)
            mock_conn_crud.update = AsyncMock()
            mock_conn_crud.create = AsyncMock()

            await notion_integrations_callback(
                code="abc", state="xyz", db=mock_db, oauth_state="xyz", refresh_token_cookie="rt"
            )

        mock_conn_crud.update.assert_called_once()
        mock_conn_crud.create.assert_not_called()


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_no_connection_raises_not_found(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_notion_connection") as mock_conn_crud:
            mock_conn_crud.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundException):
                await disconnect_notion_integration(current_user=current_user_dict, db=mock_db)

    @pytest.mark.asyncio
    async def test_revokes_the_connection(self, mock_db, current_user_dict):
        connection = {"id": uuid7(), "revoked_at": None}
        with patch(f"{MODULE}.crud_notion_connection") as mock_conn_crud:
            mock_conn_crud.get = AsyncMock(return_value=connection)
            mock_conn_crud.update = AsyncMock()

            result = await disconnect_notion_integration(current_user=current_user_dict, db=mock_db)

        assert result == {"status": "disconnected"}
        mock_conn_crud.update.assert_called_once()
