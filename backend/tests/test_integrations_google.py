"""Unit tests for the Google integrations connect/callback/disconnect routes.

Google's own endpoints and the CRUD layer are mocked (never hit over the network / a real
DB) via patches on integrations_google's own imported names — same convention as
test_oauth_google.py."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from uuid6 import uuid7

from src.app.api.v1.integrations_google import (
    connect_google_integrations,
    disconnect_google_integration,
    google_integrations_callback,
)
from src.app.core.exceptions.http_exceptions import NotFoundException, UnauthorizedException

MODULE = "src.app.api.v1.integrations_google"


class TestConnect:
    @pytest.mark.asyncio
    async def test_sets_state_cookie_and_redirects(self, current_user_dict):
        response = await connect_google_integrations(current_user=current_user_dict)
        assert response.status_code == 307
        assert "integrations_oauth_state" in response.headers.get("set-cookie", "")


class TestCallback:
    @pytest.mark.asyncio
    async def test_state_mismatch_rejected(self, mock_db):
        with pytest.raises(UnauthorizedException, match="Invalid OAuth state."):
            await google_integrations_callback(
                code="abc", state="expected", db=mock_db, oauth_state="different", refresh_token_cookie="rt"
            )

    @pytest.mark.asyncio
    async def test_missing_state_cookie_rejected(self, mock_db):
        with pytest.raises(UnauthorizedException, match="Invalid OAuth state."):
            await google_integrations_callback(
                code="abc", state="expected", db=mock_db, oauth_state=None, refresh_token_cookie="rt"
            )

    @pytest.mark.asyncio
    async def test_missing_refresh_cookie_rejected(self, mock_db):
        with pytest.raises(UnauthorizedException, match="Not authenticated."):
            await google_integrations_callback(
                code="abc", state="s", db=mock_db, oauth_state="s", refresh_token_cookie=None
            )

    @pytest.mark.asyncio
    async def test_invalid_refresh_token_rejected(self, mock_db):
        with patch(f"{MODULE}.verify_token", new=AsyncMock(return_value=None)):
            with pytest.raises(UnauthorizedException, match="Not authenticated."):
                await google_integrations_callback(
                    code="abc", state="s", db=mock_db, oauth_state="s", refresh_token_cookie="expired"
                )

    @pytest.mark.asyncio
    async def test_creates_both_connections_when_none_exist(self, mock_db):
        user_id = uuid7()
        payload = type("P", (), {"sub": str(user_id)})()

        with (
            patch(f"{MODULE}.verify_token", new=AsyncMock(return_value=payload)),
            patch(
                f"{MODULE}.exchange_code_for_tokens",
                new=AsyncMock(
                    return_value={"access_token": "g-access", "refresh_token": "g-refresh", "expires_in": 3600}
                ),
            ),
            patch(f"{MODULE}.gmail_get_profile", new=AsyncMock(return_value={"emailAddress": "person@example.com"})),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.trigger_onboarding_run", new=AsyncMock()) as mock_trigger_onboarding,
        ):
            mock_crud.get = AsyncMock(return_value=None)
            mock_crud.create = AsyncMock()

            redirect = await google_integrations_callback(
                code="abc", state="s", db=mock_db, oauth_state="s", refresh_token_cookie="valid-refresh"
            )

        assert redirect.status_code == 307
        assert mock_crud.create.call_count == 2
        mock_trigger_onboarding.assert_awaited_once_with(mock_db, user_id)
        created_types = {call.kwargs["object"].type for call in mock_crud.create.call_args_list}
        assert created_types == {"email", "calendar"}
        for call in mock_crud.create.call_args_list:
            created = call.kwargs["object"]
            assert created.user_id == user_id
            assert created.external_account_identifier == "person@example.com"
            assert created.access_token != "g-access"  # encrypted, not plaintext

    @pytest.mark.asyncio
    async def test_upserts_existing_connection_and_clears_prior_revoke(self, mock_db):
        user_id = uuid7()
        payload = type("P", (), {"sub": str(user_id)})()
        existing = {"id": uuid7()}

        with (
            patch(f"{MODULE}.verify_token", new=AsyncMock(return_value=payload)),
            patch(
                f"{MODULE}.exchange_code_for_tokens",
                new=AsyncMock(return_value={"access_token": "g-access", "expires_in": 3600}),
            ),
            patch(f"{MODULE}.gmail_get_profile", new=AsyncMock(return_value={"emailAddress": "person@example.com"})),
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.trigger_onboarding_run", new=AsyncMock()),
        ):
            mock_crud.get = AsyncMock(return_value=existing)
            mock_crud.update = AsyncMock()
            mock_crud.create = AsyncMock()

            await google_integrations_callback(
                code="abc", state="s", db=mock_db, oauth_state="s", refresh_token_cookie="valid-refresh"
            )

        mock_crud.create.assert_not_called()
        assert mock_crud.update.call_count == 2
        for call in mock_crud.update.call_args_list:
            assert call.kwargs["id"] == existing["id"]
            assert call.kwargs["object"]["revoked_at"] is None


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_no_connection_returns_not_found(self, mock_db, current_user_dict):
        with patch(f"{MODULE}.crud_integration_connections") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundException):
                await disconnect_google_integration(
                    integration_type="email", current_user=current_user_dict, db=mock_db
                )

    @pytest.mark.asyncio
    async def test_already_revoked_returns_not_found(self, mock_db, current_user_dict):
        connection = {"id": uuid7(), "revoked_at": datetime.now(UTC)}
        with patch(f"{MODULE}.crud_integration_connections") as mock_crud:
            mock_crud.get = AsyncMock(return_value=connection)
            with pytest.raises(NotFoundException):
                await disconnect_google_integration(
                    integration_type="email", current_user=current_user_dict, db=mock_db
                )

    @pytest.mark.asyncio
    async def test_disconnect_with_active_sibling_does_not_revoke_with_google(self, mock_db, current_user_dict):
        connection = {
            "id": uuid7(),
            "revoked_at": None,
            "access_token": "ciphertext",
            "watch_channel_id": None,
            "watch_resource_id": None,
            "watch_expires_at": None,
        }
        active_sibling = {"id": uuid7(), "revoked_at": None}

        with (
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.revoke_google_token", new=AsyncMock()) as mock_revoke,
        ):
            mock_crud.get = AsyncMock(side_effect=[connection, active_sibling])
            mock_crud.update = AsyncMock()

            result = await disconnect_google_integration(
                integration_type="email", current_user=current_user_dict, db=mock_db
            )

        assert result == {"status": "disconnected"}
        mock_revoke.assert_not_called()
        mock_crud.update.assert_called_once()
        assert mock_crud.update.call_args.kwargs["object"]["revoked_at"] is not None

    @pytest.mark.asyncio
    async def test_disconnect_last_sibling_revokes_with_google(self, mock_db, current_user_dict):
        connection = {
            "id": uuid7(),
            "revoked_at": None,
            "access_token": "ciphertext",
            "watch_channel_id": "chan-1",
            "watch_resource_id": "res-1",
            "watch_expires_at": datetime.now(UTC),
        }

        with (
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.decrypt_token", return_value="plaintext-access-token"),
            patch(f"{MODULE}.calendar_stop_watch", new=AsyncMock()) as mock_stop_watch,
            patch(f"{MODULE}.revoke_google_token", new=AsyncMock()) as mock_revoke,
        ):
            # No sibling row at all — the other type was never connected.
            mock_crud.get = AsyncMock(side_effect=[connection, None])
            mock_crud.update = AsyncMock()

            result = await disconnect_google_integration(
                integration_type="calendar", current_user=current_user_dict, db=mock_db
            )

        assert result == {"status": "disconnected"}
        mock_stop_watch.assert_called_once_with("plaintext-access-token", "chan-1", "res-1")
        mock_revoke.assert_called_once_with("plaintext-access-token")

    @pytest.mark.asyncio
    async def test_stop_watch_failure_does_not_block_disconnect(self, mock_db, current_user_dict):
        connection = {
            "id": uuid7(),
            "revoked_at": None,
            "access_token": "ciphertext",
            "watch_channel_id": "chan-1",
            "watch_resource_id": "res-1",
            "watch_expires_at": None,
        }
        active_sibling = {"id": uuid7(), "revoked_at": None}

        error_response = httpx.Response(status_code=404, request=httpx.Request("POST", "https://example.com"))

        with (
            patch(f"{MODULE}.crud_integration_connections") as mock_crud,
            patch(f"{MODULE}.decrypt_token", return_value="plaintext-access-token"),
            patch(
                f"{MODULE}.calendar_stop_watch",
                new=AsyncMock(
                    side_effect=httpx.HTTPStatusError(
                        "not found", request=error_response.request, response=error_response
                    )
                ),
            ),
        ):
            mock_crud.get = AsyncMock(side_effect=[connection, active_sibling])
            mock_crud.update = AsyncMock()

            result = await disconnect_google_integration(
                integration_type="calendar", current_user=current_user_dict, db=mock_db
            )

        assert result == {"status": "disconnected"}
        mock_crud.update.assert_called_once()
