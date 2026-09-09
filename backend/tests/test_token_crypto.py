"""Round-trip tests for core/crypto.py's Fernet-based token encryption."""

import pytest

from src.app.core.crypto import decrypt_token, encrypt_token


class TestTokenCrypto:
    def test_round_trip(self):
        plaintext = "ya29.some-google-access-token"
        ciphertext = encrypt_token(plaintext)

        assert ciphertext != plaintext
        assert decrypt_token(ciphertext) == plaintext

    def test_different_plaintexts_produce_different_ciphertexts(self):
        assert encrypt_token("token-a") != encrypt_token("token-b")

    def test_same_plaintext_encrypted_twice_produces_different_ciphertext(self):
        """Fernet includes a random IV/nonce per encryption — not deterministic."""
        plaintext = "same-token"
        assert encrypt_token(plaintext) != encrypt_token(plaintext)

    def test_invalid_ciphertext_raises_value_error(self):
        with pytest.raises(ValueError, match="Failed to decrypt token"):
            decrypt_token("not-a-real-fernet-token")

    def test_tampered_ciphertext_raises_value_error(self):
        ciphertext = encrypt_token("a-real-token")
        tampered = ciphertext[:-4] + "abcd"

        with pytest.raises(ValueError, match="Failed to decrypt token"):
            decrypt_token(tampered)
