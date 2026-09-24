"""Unit tests for embedding_model — SentenceTransformer itself is mocked here; loading
the real model is exercised manually per project-manager verification steps, not in unit
tests (downloading real model weights has no place in a fast unit-test suite)."""

from unittest.mock import MagicMock, patch

import pytest

from src.app.core.config import settings
from src.app.core.llm import embedding_model


class TestInitEmbeddingModel:
    @pytest.mark.asyncio
    async def test_loads_model_and_matches_configured_dimension(self):
        fake_model = MagicMock()
        fake_model.get_embedding_dimension.return_value = settings.EMBEDDING_DIMENSION

        with patch.object(embedding_model, "SentenceTransformer", return_value=fake_model):
            await embedding_model.init_embedding_model()

        assert embedding_model._model is fake_model

    @pytest.mark.asyncio
    async def test_raises_on_dimension_mismatch(self):
        fake_model = MagicMock()
        fake_model.get_embedding_dimension.return_value = settings.EMBEDDING_DIMENSION + 1

        with patch.object(embedding_model, "SentenceTransformer", return_value=fake_model):
            with pytest.raises(ValueError, match="dimension"):
                await embedding_model.init_embedding_model()


class TestEmbedText:
    @pytest.mark.asyncio
    async def test_embed_text_returns_a_plain_list(self):
        fake_vector = MagicMock()
        fake_vector.tolist.return_value = [0.1, 0.2, 0.3]
        fake_model = MagicMock()
        fake_model.encode.return_value = fake_vector

        with patch.object(embedding_model, "_model", fake_model):
            result = await embedding_model.embed_text("hello")

        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_raises_if_model_not_initialized(self):
        with patch.object(embedding_model, "_model", None):
            with pytest.raises(RuntimeError):
                await embedding_model.embed_text("hello")


class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_encodes_whole_list_in_one_call(self):
        fake_matrix = MagicMock()
        fake_matrix.tolist.return_value = [[0.1, 0.2], [0.3, 0.4]]
        fake_model = MagicMock()
        fake_model.encode.return_value = fake_matrix

        with patch.object(embedding_model, "_model", fake_model):
            result = await embedding_model.embed_texts(["a", "b"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        fake_model.encode.assert_called_once_with(["a", "b"])

    @pytest.mark.asyncio
    async def test_raises_if_model_not_initialized(self):
        with patch.object(embedding_model, "_model", None):
            with pytest.raises(RuntimeError):
                await embedding_model.embed_texts(["hello"])
