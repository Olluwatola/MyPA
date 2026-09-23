"""SimHash — a similarity-preserving fingerprint used by the edit-path 3-stage gate's
stage 2 (see core/notion/edit_gate.py) to tell a meaningful content change apart from a
typo/formatting touch, without ever needing the old text stored (see PRD §6.5).

Hand-rolled, not a dependency — no `simhash` package is installed, and the algorithm is
~30 lines; pulling in a niche package for this would be disproportionate (see the Feature
1.7 planning notes).

Deliberately NOT Python's built-in `hash()`: that's salted per-process (`PYTHONHASHSEED`)
specifically to resist hash-flooding attacks, so the same text would fingerprint
differently across worker restarts — useless for a value persisted and compared later.
`blake2b` is stable and fast.
"""

import hashlib
import re

_TOKEN_RE = re.compile(r"\w+")

DEFAULT_HASH_BITS = 64


def _token_hash(token: str, hash_bits: int) -> int:
    digest_size = max(1, hash_bits // 8)
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=digest_size).digest()
    return int.from_bytes(digest, byteorder="big")


def compute_simhash(text: str, hash_bits: int = DEFAULT_HASH_BITS) -> int:
    """Tokenizes on word boundaries (lowercased), hashes each token, and accumulates a
    weighted bit-vector across all tokens — bit `i` of the final hash is set if more
    tokens had bit `i` set than not. An empty/whitespace-only text hashes to 0."""
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return 0

    weights = [0] * hash_bits
    for token in tokens:
        token_hash = _token_hash(token, hash_bits)
        for bit in range(hash_bits):
            if (token_hash >> bit) & 1:
                weights[bit] += 1
            else:
                weights[bit] -= 1

    result = 0
    for bit in range(hash_bits):
        if weights[bit] > 0:
            result |= 1 << bit
    return result


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
