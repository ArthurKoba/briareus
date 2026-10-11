"""Shared immutable credential primitives: no Identity↔Access source dependency.

Argon2id parameters, PHC encoded verification and original random/hash token
functions preserve the previously accepted cryptographic formats byte-for-byte.
No bearer issuance, SQL access, authority or secret logging is introduced.
"""

from __future__ import annotations

import hashlib
import secrets

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

_ARGON2_ITERATIONS = 3
_ARGON2_LANES = 4
_ARGON2_MEMORY_KIB = 64 * 1024
_ARGON2_LENGTH = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    kdf = Argon2id(
        salt=salt,
        length=_ARGON2_LENGTH,
        iterations=_ARGON2_ITERATIONS,
        lanes=_ARGON2_LANES,
        memory_cost=_ARGON2_MEMORY_KIB,
    )
    return kdf.derive_phc_encoded(password.encode())


def verify_password(password: str, encoded: str) -> bool:
    try:
        Argon2id.verify_phc_encoded(password.encode(), encoded)
    except Exception:
        return False
    return True


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)
