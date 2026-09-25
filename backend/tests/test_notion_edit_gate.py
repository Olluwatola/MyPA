"""Unit tests for the edit-path 3-stage gate (core/notion/edit_gate.py) — the three
required scenarios (unchanged timestamp, minor fingerprint delta, real change) plus the
confirmed one-call-per-changed-block override (never batched)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.notion.client import NotionBlock
from src.app.core.notion.edit_gate import process_changed_block
from src.app.core.notion.simhash import compute_simhash
from src.app.crud.crud_tasks import crud_tasks
from src.app.schemas.notion_classification import (
    NotionAnchoredClassificationResult,
    NotionAnchoredItemOutcome,
    NotionExtractedItem,
    NotionFreshClassificationResult,
)

MODULE = "src.app.core.notion.edit_gate"
PERSISTENCE = "src.app.core.notion.persistence"


def _block(block_id: str, text: str, edited_at: datetime, block_type: str = "paragraph") -> NotionBlock:
    return NotionBlock(
        id=block_id, type=block_type, plain_text=text, last_edited_time=edited_at, has_children=False, parent={}, raw={}
    )


@pytest.fixture(autouse=True)
def no_open_goals():
    """Most tests don't care about goal linking — the user has no open goals."""
    with patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=[])) as mock_load:
        yield mock_load


class TestUnchangedTimestamp:
    @pytest.mark.asyncio
    async def test_no_fetch_or_llm_call_when_timestamp_unchanged(self, mock_db):
        edited_at = datetime.now(UTC)
        block = _block("block-1", "finish the deck", edited_at)
        existing_sync = {"id": uuid7(), "last_edited_time": edited_at, "content_fingerprint": 123}

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock()) as mock_classify,
        ):
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_classify.assert_not_called()
        mock_sync.update.assert_not_called()


class TestMinorFingerprintDelta:
    @pytest.mark.asyncio
    async def test_trivial_edit_refreshes_watermark_without_llm_call(self, mock_db):
        old_text = "finish the deck for friday"
        new_text = "finish the deck for friday."  # punctuation-only edit
        old_fingerprint = compute_simhash(old_text)
        old_time = datetime(2026, 1, 1, tzinfo=UTC)
        new_time = datetime(2026, 1, 2, tzinfo=UTC)
        block = _block("block-1", new_text, new_time)
        existing_sync = {"id": uuid7(), "last_edited_time": old_time, "content_fingerprint": old_fingerprint}

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock()) as mock_classify,
            patch(f"{MODULE}.settings") as mock_settings,
        ):
            mock_settings.NOTION_EDIT_SIMHASH_UNCHANGED_THRESHOLD = 3
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_classify.assert_not_called()
        mock_sync.update.assert_called_once()
        _, kwargs = mock_sync.update.call_args
        assert kwargs["object"]["last_edited_time"] == new_time


class TestRealChange:
    @pytest.mark.asyncio
    async def test_meaningful_edit_reaches_classification(self, mock_db):
        old_text = "finish the deck"
        new_text = "schedule a dentist appointment for next month"
        old_time = datetime(2026, 1, 1, tzinfo=UTC)
        new_time = datetime(2026, 1, 2, tzinfo=UTC)
        block = _block("block-1", new_text, new_time)
        existing_sync = {
            "id": uuid7(),
            "last_edited_time": old_time,
            "content_fingerprint": compute_simhash(old_text),
        }
        fresh_result = NotionFreshClassificationResult(outcome="not_actionable", summary="not actionable")

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock(return_value=fresh_result)) as mock_classify,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
        ):
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()
            mock_link.get_multi = AsyncMock(return_value={"data": []})

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_classify.assert_called_once()
        mock_persist.assert_called_once()


class TestMultiBlockEditEvent:
    @pytest.mark.asyncio
    async def test_each_changed_block_gets_its_own_separate_classification_call(self, mock_db):
        """The confirmed 2026-09-23 override: N changed blocks in one event -> N
        classification calls, never one batched call covering all of them."""
        new_time = datetime(2026, 1, 2, tzinfo=UTC)
        blocks = [
            _block("block-1", "schedule the dentist", new_time),
            _block("block-2", "email the client about the deck", new_time),
        ]
        fresh_result = NotionFreshClassificationResult(outcome="not_actionable", summary="x")

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock(return_value=fresh_result)) as mock_classify,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()),
        ):
            mock_sync.get = AsyncMock(return_value=None)  # never seen before -> always classify
            mock_sync.create = AsyncMock(return_value={"id": uuid7()})
            mock_link.get_multi = AsyncMock(return_value={"data": []})

            for block in blocks:
                await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", block.id, blocks)

        assert mock_classify.call_count == 2


class TestAnchoredWithDeletedTask:
    """A soft-deleted task keeps its notion_block_link row, so its line stays on the
    anchored path: the classifier still sees it as "already handled" (not re-created),
    while a genuinely new item on the same line is still created."""

    @staticmethod
    def _changed_block_setup():
        old_time = datetime(2026, 1, 1, tzinfo=UTC)
        new_time = datetime(2026, 1, 2, tzinfo=UTC)
        block = _block("block-1", "email the client and book the venue", new_time)
        existing_sync = {"id": uuid7(), "last_edited_time": old_time, "content_fingerprint": compute_simhash("x")}
        return block, existing_sync

    @pytest.mark.asyncio
    async def test_deleted_task_is_shown_to_classifier_and_only_new_item_created(self, mock_db):
        block, existing_sync = self._changed_block_setup()
        deleted_task_id = uuid7()
        links = [{"item_type": "task", "item_id": deleted_task_id}]
        deleted_task = {"id": deleted_task_id, "title": "Email the client", "description": None, "is_deleted": True}
        anchored_result = NotionAnchoredClassificationResult(
            summary="email client, book venue",
            existing_items=[NotionAnchoredItemOutcome(item_id=deleted_task_id, disposition="unchanged")],
            additional_items=[NotionExtractedItem(item_type="task", title="Book the venue", confidence=0.9)],
        )

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_tasks") as mock_tasks,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock()) as mock_fresh,
            patch(f"{MODULE}.reclassify_anchored_block", new=AsyncMock(return_value=anchored_result)) as mock_anchored,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
        ):
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_tasks.get = AsyncMock(return_value=deleted_task)

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_fresh.assert_not_called()
        assert "is_deleted" not in mock_tasks.get.call_args.kwargs
        existing_items = mock_anchored.call_args.args[2]
        assert existing_items == [
            {"item_id": str(deleted_task_id), "item_type": "task", "title": "Email the client", "description": None}
        ]
        actions = mock_persist.call_args.args[5]
        assert [(action.kind, action.title) for action in actions] == [("create", "Book the venue")]

    @pytest.mark.asyncio
    async def test_update_aimed_at_deleted_task_changes_nothing_end_to_end(self, mock_db):
        block, existing_sync = self._changed_block_setup()
        deleted_task_id = uuid7()
        links = [{"item_type": "task", "item_id": deleted_task_id}]
        deleted_task = {
            "id": deleted_task_id,
            "title": "Email the client",
            "description": None,
            "is_deleted": True,
            "title_manually_set": False,
            "description_manually_set": False,
            "urgency_manually_set": False,
            "effort_level_manually_set": False,
        }
        anchored_result = NotionAnchoredClassificationResult(
            summary="email client today",
            existing_items=[
                NotionAnchoredItemOutcome(
                    item_id=deleted_task_id, disposition="updated", updated_title="Email the client today"
                )
            ],
        )

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.reclassify_anchored_block", new=AsyncMock(return_value=anchored_result)),
            patch.object(crud_tasks, "get", new=AsyncMock(return_value=deleted_task)),
            patch.object(crud_tasks, "update", new=AsyncMock()) as mock_update,
            patch.object(crud_tasks, "create", new=AsyncMock()) as mock_create,
            patch(f"{PERSISTENCE}.crud_memory_extraction_records") as mock_records,
            patch(f"{PERSISTENCE}.crud_embeddings") as mock_embeddings,
            patch(f"{PERSISTENCE}.embed_text", new=AsyncMock(return_value=[0.0] * 384)),
        ):
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_records.create = AsyncMock(return_value={"id": uuid7()})
            mock_embeddings.create = AsyncMock()
            mock_db.commit = AsyncMock()
            mock_db.rollback = AsyncMock()

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_update.assert_not_called()
        mock_create.assert_not_called()
        mock_db.commit.assert_called_once()


class TestAnchoredWithDeletedGoal:
    """Required proof (b) for goals: a soft-deleted goal keeps its link row, so its Notion
    line stays anchored and the goal is never re-created — a new item on the line still is."""

    @pytest.mark.asyncio
    async def test_deleted_goal_is_shown_to_classifier_and_only_new_item_created(self, mock_db):
        block, existing_sync = TestAnchoredWithDeletedTask._changed_block_setup()
        deleted_goal_id = uuid7()
        links = [{"item_type": "goal", "item_id": deleted_goal_id}]
        deleted_goal = {"id": deleted_goal_id, "title": "Launch ClientPal", "description": None, "is_deleted": True}
        anchored_result = NotionAnchoredClassificationResult(
            summary="launch clientpal, book the venue",
            existing_items=[NotionAnchoredItemOutcome(item_id=deleted_goal_id, disposition="unchanged")],
            additional_items=[NotionExtractedItem(item_type="task", title="Book the venue", confidence=0.9)],
        )

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.crud_goals") as mock_goals,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock()) as mock_fresh,
            patch(f"{MODULE}.reclassify_anchored_block", new=AsyncMock(return_value=anchored_result)) as mock_anchored,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
        ):
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_goals.get = AsyncMock(return_value=deleted_goal)

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_fresh.assert_not_called()
        assert "is_deleted" not in mock_goals.get.call_args.kwargs
        assert mock_anchored.call_args.args[2] == [
            {"item_id": str(deleted_goal_id), "item_type": "goal", "title": "Launch ClientPal", "description": None}
        ]
        actions = mock_persist.call_args.args[5]
        assert [(action.kind, action.item_type, action.title) for action in actions] == [
            ("create", "task", "Book the venue")
        ]

    @pytest.mark.asyncio
    async def test_update_aimed_at_deleted_goal_changes_nothing_end_to_end(self, mock_db):
        from src.app.crud.crud_goals import crud_goals

        block, existing_sync = TestAnchoredWithDeletedTask._changed_block_setup()
        deleted_goal_id = uuid7()
        links = [{"item_type": "goal", "item_id": deleted_goal_id}]
        deleted_goal = {
            "id": deleted_goal_id,
            "title": "Launch ClientPal",
            "description": None,
            "is_deleted": True,
            "title_manually_set": False,
            "description_manually_set": False,
        }
        anchored_result = NotionAnchoredClassificationResult(
            summary="launch clientpal in march",
            existing_items=[
                NotionAnchoredItemOutcome(
                    item_id=deleted_goal_id, disposition="updated", updated_title="Launch ClientPal in March"
                )
            ],
        )

        with (
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.reclassify_anchored_block", new=AsyncMock(return_value=anchored_result)),
            patch.object(crud_goals, "get", new=AsyncMock(return_value=deleted_goal)),
            patch.object(crud_goals, "update", new=AsyncMock()) as mock_update,
            patch.object(crud_goals, "create", new=AsyncMock()) as mock_create,
            patch(f"{PERSISTENCE}.crud_memory_extraction_records") as mock_records,
            patch(f"{PERSISTENCE}.crud_embeddings") as mock_embeddings,
            patch(f"{PERSISTENCE}.embed_text", new=AsyncMock(return_value=[0.0] * 384)),
        ):
            mock_sync.get = AsyncMock(return_value=existing_sync)
            mock_sync.update = AsyncMock()
            mock_link.get_multi = AsyncMock(return_value={"data": links})
            mock_records.create = AsyncMock(return_value={"id": uuid7()})
            mock_embeddings.create = AsyncMock()
            mock_db.commit = AsyncMock()
            mock_db.rollback = AsyncMock()

            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])

        mock_update.assert_not_called()
        mock_create.assert_not_called()
        mock_db.commit.assert_called_once()


class TestNotionTaskGoalLink:
    """Required proof (f), Notion half: a Notion-created task is linked to an open goal
    only when the classifier is confident; goals themselves never get a link."""

    GOAL_ID = uuid7()
    OPEN_GOALS = [{"id": GOAL_ID, "title": "Launch ClientPal", "description": None, "horizon": "short_term"}]

    async def _fresh_actions(self, mock_db, items):
        block = _block("block-1", "draft the landing page", datetime(2026, 1, 2, tzinfo=UTC))
        fresh_result = NotionFreshClassificationResult(outcome="actionable", summary="landing page", items=items)
        with (
            patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=self.OPEN_GOALS)),
            patch(f"{MODULE}.crud_notion_block_sync") as mock_sync,
            patch(f"{MODULE}.crud_notion_block_link") as mock_link,
            patch(f"{MODULE}.classify_fresh_block", new=AsyncMock(return_value=fresh_result)) as mock_classify,
            patch(f"{MODULE}.persist_notion_block_outcome", new=AsyncMock()) as mock_persist,
        ):
            mock_sync.get = AsyncMock(return_value=None)
            mock_sync.create = AsyncMock(return_value={"id": uuid7()})
            mock_link.get_multi = AsyncMock(return_value={"data": []})
            await process_changed_block(mock_db, AsyncMock(), uuid7(), "page-1", "block-1", [block])
        return mock_persist.call_args.args[5], mock_classify

    @pytest.mark.asyncio
    async def test_confident_task_link_is_carried_to_persistence(self, mock_db):
        item = NotionExtractedItem(
            item_type="task", title="Draft landing page", confidence=0.9, goal_ref=1, goal_link_confidence=0.9
        )
        actions, mock_classify = await self._fresh_actions(mock_db, [item])
        assert actions[0].goal_id == self.GOAL_ID
        assert mock_classify.call_args.args[2] == self.OPEN_GOALS

    @pytest.mark.asyncio
    async def test_unsure_task_link_is_dropped(self, mock_db):
        item = NotionExtractedItem(
            item_type="task", title="Draft landing page", confidence=0.9, goal_ref=1, goal_link_confidence=0.5
        )
        actions, _ = await self._fresh_actions(mock_db, [item])
        assert actions[0].goal_id is None

    @pytest.mark.asyncio
    async def test_goal_item_never_gets_a_link(self, mock_db):
        item = NotionExtractedItem(
            item_type="goal", title="Grow the newsletter", confidence=0.9, goal_ref=1, goal_link_confidence=0.95
        )
        actions, _ = await self._fresh_actions(mock_db, [item])
        assert actions[0].goal_id is None
