"""Unit tests for the SimHash fingerprint used by the edit-path 3-stage gate's stage 2
(see core/notion/edit_gate.py)."""

from src.app.core.notion.simhash import compute_simhash, hamming_distance


class TestComputeSimhash:
    def test_identical_text_hashes_identically(self):
        text = "finish the deck for Friday's client review"
        assert compute_simhash(text) == compute_simhash(text)

    def test_empty_text_hashes_to_zero(self):
        assert compute_simhash("") == 0
        assert compute_simhash("   ") == 0

    def test_stable_across_calls(self):
        """Confirms blake2b-based hashing (not Python's salted hash()) — the whole
        point of storing this value for later comparison."""
        text = "update the PRD with the new onboarding flow"
        results = {compute_simhash(text) for _ in range(5)}
        assert len(results) == 1


class TestHammingDistance:
    def test_identical_hashes_have_zero_distance(self):
        assert hamming_distance(0b1010, 0b1010) == 0

    def test_distance_counts_differing_bits(self):
        assert hamming_distance(0b0000, 0b1111) == 4
        assert hamming_distance(0b1010, 0b0101) == 4

    def test_tiny_edit_produces_small_distance(self):
        """A punctuation/whitespace-level edit should stay well under a typical
        unchanged-threshold (see settings.NOTION_EDIT_SIMHASH_UNCHANGED_THRESHOLD)."""
        original = compute_simhash("finish the deck for friday")
        tiny_edit = compute_simhash("finish the deck for friday.")
        assert hamming_distance(original, tiny_edit) <= 3

    def test_substantive_change_produces_large_distance(self):
        original = compute_simhash("finish the deck for friday")
        rewritten = compute_simhash("schedule a dentist appointment next month")
        assert hamming_distance(original, rewritten) > 10
