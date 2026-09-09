"""Unit tests for POST /api/v1/memory/ingest."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.app.api.v1.memory import MemoryIngestRequest, write_memory_ingest


class TestWriteMemoryIngest:
    @pytest.mark.asyncio
    async def test_delegates_to_extraction_pipeline(self, mock_db, current_user_dict):
        payload = MemoryIngestRequest(source_type="conversation", source_channel="in_app", content="Buy milk")
        expected = {"id": uuid4(), "summary": "Buy milk"}

        with patch(
            "src.app.api.v1.memory.run_memory_extraction_pipeline", AsyncMock(return_value=expected)
        ) as mock_pipeline:
            result = await write_memory_ingest(payload, current_user_dict, mock_db)

        assert result == expected
        mock_pipeline.assert_called_once_with(
            db=mock_db,
            user_id=current_user_dict["id"],
            source_type="conversation",
            source_channel="in_app",
            content="Buy milk",
        )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            MemoryIngestRequest(source_type="conversation", content="Buy milk", extra_field="nope")

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            MemoryIngestRequest(source_type="conversation", content="")
