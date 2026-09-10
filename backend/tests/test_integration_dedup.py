"""Unit tests for core/integrations/dedup.py's is_item_unchanged/mark_item_synced pair:
the read-only unchanged/changed/never-seen decision, the create-vs-update upsert shape,
and the concurrent-first-sync IntegrityError race being caught and rolled back rather
than crashing the caller's batch loop."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from src.app.core.integrations import dedup

MODULE = "src.app.core.integrations.dedup"


class TestIsItemUnchanged:
    @pytest.mark.asyncio
    async def test_never_seen_returns_false(self, mock_db):
        with patch(f"{MODULE}.crud_ingestion_sync") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)

            unchanged, existing_row = await dedup.is_item_unchanged(mock_db, uuid7(), "email", "m1", "content")

        assert unchanged is False
        assert existing_row is None

    @pytest.mark.asyncio
    async def test_matching_fingerprint_returns_true(self, mock_db):
        content = "the exact same content"
        existing = {"content_fingerprint": dedup._fingerprint(content)}
        with patch(f"{MODULE}.crud_ingestion_sync") as mock_crud:
            mock_crud.get = AsyncMock(return_value=existing)

            unchanged, existing_row = await dedup.is_item_unchanged(mock_db, uuid7(), "email", "m1", content)

        assert unchanged is True
        assert existing_row is existing

    @pytest.mark.asyncio
    async def test_changed_content_returns_false(self, mock_db):
        existing = {"content_fingerprint": dedup._fingerprint("old content")}
        with patch(f"{MODULE}.crud_ingestion_sync") as mock_crud:
            mock_crud.get = AsyncMock(return_value=existing)

            unchanged, existing_row = await dedup.is_item_unchanged(mock_db, uuid7(), "email", "m1", "new content")

        assert unchanged is False
        # The row still exists (just stale) — returned anyway so the caller can pass it
        # straight into mark_item_synced without a second fetch.
        assert existing_row is existing


class TestMarkItemSynced:
    @pytest.mark.asyncio
    async def test_no_existing_row_creates_one(self, mock_db):
        user_id = uuid7()
        record_id = uuid7()

        with patch(f"{MODULE}.crud_ingestion_sync") as mock_crud:
            mock_crud.create = AsyncMock()

            await dedup.mark_item_synced(mock_db, user_id, "calendar", "e1", "content", record_id, existing_row=None)

        mock_crud.get.assert_not_called()
        mock_crud.create.assert_called_once()
        created = mock_crud.create.call_args.kwargs["object"]
        assert created.user_id == user_id
        assert created.source_type == "calendar"
        assert created.external_id == "e1"
        assert created.content_fingerprint == dedup._fingerprint("content")
        assert created.memory_record_id == record_id

    @pytest.mark.asyncio
    async def test_existing_row_updates_fingerprint_and_record_id(self, mock_db):
        """`existing_row` is passed straight in (as `is_item_unchanged` would have
        returned it) — mark_item_synced must not re-fetch it itself."""
        existing_id = uuid7()
        new_record_id = uuid7()

        with patch(f"{MODULE}.crud_ingestion_sync") as mock_crud:
            mock_crud.update = AsyncMock()

            await dedup.mark_item_synced(
                mock_db,
                uuid7(),
                "email",
                "m1",
                "new content",
                new_record_id,
                existing_row={"id": existing_id, "content_fingerprint": "stale"},
            )

        mock_crud.get.assert_not_called()
        mock_crud.update.assert_called_once_with(
            db=mock_db,
            object={"content_fingerprint": dedup._fingerprint("new content"), "memory_record_id": new_record_id},
            id=existing_id,
        )

    @pytest.mark.asyncio
    async def test_integrity_error_on_create_is_caught_and_rolled_back(self, mock_db):
        """Two ingestion paths racing to first-sync the same never-before-seen item —
        the loser's create() raises IntegrityError on the unique constraint. Must not
        propagate, must roll back the session."""
        with patch(f"{MODULE}.crud_ingestion_sync") as mock_crud:
            mock_crud.create = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("duplicate key")))

            await dedup.mark_item_synced(mock_db, uuid7(), "email", "m1", "content", uuid7(), existing_row=None)

        mock_db.rollback.assert_called_once()
