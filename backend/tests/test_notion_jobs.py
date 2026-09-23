"""Unit tests for the Notion ARQ job functions (core/notion/jobs.py): Retry-on-transient
-failure behavior (mirrors test_integration_jobs.py's pattern) and per-block fault
isolation for a multi-block edit event."""

from unittest.mock import AsyncMock, patch

import pytest
from arq import Retry
from uuid6 import uuid7

MODULE = "src.app.core.notion.jobs"


class TestRunNotionInitialExtraction:
    @pytest.mark.asyncio
    async def test_unresolvable_page_is_skipped_not_retried(self):
        from src.app.core.notion.jobs import run_notion_initial_extraction

        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}.resolve_user_for_page", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.run_initial_extraction", new=AsyncMock()) as mock_run,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            await run_notion_initial_extraction({"job_try": 1}, "page-1")

        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_transient_failure_raises_retry(self):
        from src.app.core.notion.jobs import run_notion_initial_extraction

        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}.resolve_user_for_page", new=AsyncMock(return_value=(uuid7(), "token"))),
            patch(f"{MODULE}.run_initial_extraction", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            with pytest.raises(Retry):
                await run_notion_initial_extraction({"job_try": 1}, "page-1")


class TestProcessNotionContentUpdated:
    @pytest.mark.asyncio
    async def test_one_bad_block_does_not_abort_the_rest(self):
        """Per-block fault isolation — matches every other per-item loop in this
        codebase (process_gmail_notification, run_onboarding_ingestion, etc.)."""
        from src.app.core.notion.jobs import process_notion_content_updated

        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}.resolve_user_for_page", new=AsyncMock(return_value=(uuid7(), "token"))),
            patch(f"{MODULE}.fetch_all_blocks_recursive", new=AsyncMock(return_value=[])),
            patch(
                f"{MODULE}.process_changed_block", new=AsyncMock(side_effect=[RuntimeError("boom"), None])
            ) as mock_process,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            ctx = {"job_try": 1, "redis": AsyncMock()}
            await process_notion_content_updated(ctx, "page-1", ["block-1", "block-2"])

        assert mock_process.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_failure_raises_retry(self):
        from src.app.core.notion.jobs import process_notion_content_updated

        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}.resolve_user_for_page", new=AsyncMock(return_value=(uuid7(), "token"))),
            patch(f"{MODULE}.fetch_all_blocks_recursive", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            ctx = {"job_try": 1, "redis": AsyncMock()}
            with pytest.raises(Retry):
                await process_notion_content_updated(ctx, "page-1", ["block-1"])


class TestReconcileNotionPages:
    @pytest.mark.asyncio
    async def test_no_active_users_skips_entirely(self):
        from src.app.core.notion.jobs import reconcile_notion_pages

        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}._active_notion_user_ids", new=AsyncMock(return_value=set())),
            patch(f"{MODULE}.crud_notion_connection") as mock_conn,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_conn.get_multi = AsyncMock()
            await reconcile_notion_pages({"redis": AsyncMock()})

        mock_conn.get_multi.assert_not_called()

    @pytest.mark.asyncio
    async def test_one_bad_connection_does_not_abort_the_sweep(self):
        from src.app.core.notion.jobs import reconcile_notion_pages

        user_id = uuid7()
        connections = {"data": [{"id": uuid7(), "user_id": user_id}, {"id": uuid7(), "user_id": user_id}]}
        with (
            patch(f"{MODULE}.local_session") as mock_session_factory,
            patch(f"{MODULE}._active_notion_user_ids", new=AsyncMock(return_value={user_id})),
            patch(f"{MODULE}.crud_notion_connection") as mock_conn,
            patch(
                f"{MODULE}._reconcile_one_user", new=AsyncMock(side_effect=[RuntimeError("boom"), None])
            ) as mock_reconcile,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_conn.get_multi = AsyncMock(return_value=connections)
            await reconcile_notion_pages({"redis": AsyncMock()})

        assert mock_reconcile.call_count == 2
