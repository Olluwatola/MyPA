"""Unit tests for lifespan_factory's `init_llm_on_start` gate: the embedding model in
particular loads real model weights, so a future test that boots a real TestClient(app)
for something unrelated needs a way to skip that cost — mirrors `create_tables_on_start`.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from src.app.core.config import settings
from src.app.core.setup import lifespan_factory


@pytest.mark.asyncio
async def test_init_llm_on_start_true_builds_llm_service_and_embedding_model():
    lifespan = lifespan_factory(settings, create_tables_on_start=False, init_llm_on_start=True)

    with (
        patch("src.app.core.setup.build_llm_service", MagicMock()) as mock_build_llm_service,
        patch("src.app.core.setup.init_embedding_model", AsyncMock()) as mock_init_embedding_model,
        patch("src.app.core.setup.create_redis_cache_pool", AsyncMock()),
        patch("src.app.core.setup.close_redis_cache_pool", AsyncMock()),
        patch("src.app.core.setup.create_redis_queue_pool", AsyncMock()),
        patch("src.app.core.setup.close_redis_queue_pool", AsyncMock()),
    ):
        async with lifespan(FastAPI()):
            pass

    mock_build_llm_service.assert_called_once()
    mock_init_embedding_model.assert_called_once()


@pytest.mark.asyncio
async def test_init_llm_on_start_false_skips_llm_service_and_embedding_model():
    lifespan = lifespan_factory(settings, create_tables_on_start=False, init_llm_on_start=False)

    with (
        patch("src.app.core.setup.build_llm_service", MagicMock()) as mock_build_llm_service,
        patch("src.app.core.setup.init_embedding_model", AsyncMock()) as mock_init_embedding_model,
        patch("src.app.core.setup.create_redis_cache_pool", AsyncMock()),
        patch("src.app.core.setup.close_redis_cache_pool", AsyncMock()),
        patch("src.app.core.setup.create_redis_queue_pool", AsyncMock()),
        patch("src.app.core.setup.close_redis_queue_pool", AsyncMock()),
    ):
        async with lifespan(FastAPI()):
            pass

    mock_build_llm_service.assert_not_called()
    mock_init_embedding_model.assert_not_called()
