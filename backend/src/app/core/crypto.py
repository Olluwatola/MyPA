"""Reversible encryption for third-party OAuth tokens (Google access/refresh tokens,
Calendar webhook channel tokens) — a distinct security boundary from `core/security.py`
(one-way password hashing, JWT signing), so it lives in its own module rather than being
folded into `security.py`. Keyed off `TOKEN_ENCRYPTION_KEY`, not `SECRET_KEY` — different
rotation story: rotating the JWT signing key shouldn't force re-encrypting every stored
token, and vice versa.
"""

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_fernet = Fernet(settings.TOKEN_ENCRYPTION_KEY.get_secret_value().encode())


def encrypt_token(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt token — invalid ciphertext or wrong encryption key.") from exc
