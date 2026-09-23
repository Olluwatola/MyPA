"""Unit tests for the in-memory cosine-similarity helper — the genuine gap this codebase
didn't have before Feature 1.7 (see core/llm/similarity.py)."""

from src.app.core.llm.similarity import cosine_similarity


class TestCosineSimilarity:
    def test_identical_vectors_are_maximally_similar(self):
        vector = [0.1, 0.2, 0.3, 0.4]
        assert abs(cosine_similarity(vector, vector) - 1.0) < 1e-9

    def test_orthogonal_vectors_have_zero_similarity(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_opposite_vectors_have_negative_similarity(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0

    def test_zero_vector_returns_zero_not_nan(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_scaling_does_not_change_similarity(self):
        a = [1.0, 2.0, 3.0]
        b = [2.0, 4.0, 6.0]
        assert abs(cosine_similarity(a, b) - 1.0) < 1e-9
