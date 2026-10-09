"""Derive non-interchangeable durable cryptographic subkeys from storage root.

Credential encryption and replay-sensitive command outcomes intentionally
share ONE securely provisioned at-rest root, but HKDF contexts prevent
cross-purpose key reuse. Changing CREDENTIAL_ENCRYPTION_KEY requires an
explicit database ciphertext and HMAC/index migration; no silent rotation.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _root(secret: str) -> bytes:
    try:
        Fernet(secret.encode())
        raw = base64.urlsafe_b64decode(secret.encode())
    except (ValueError, TypeError) as exc:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY must be a Fernet key") from exc
    if len(raw) != 32:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY must contain 32 random bytes")
    return raw


def _derive(secret: str, purpose: str) -> bytes:
    if not purpose.startswith("briareus.") or not purpose.endswith(".v1"):
        raise ValueError("cryptographic subkey purpose must be versioned")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"briareus-storage-domain-separation-v1",
        info=purpose.encode("ascii"),
    ).derive(_root(secret))


def fingerprint_key(secret: str) -> bytes:
    return _derive(secret, "briareus.command.fingerprint.v1")


def replay_fernet_key(secret: str) -> str:
    return base64.urlsafe_b64encode(
        _derive(secret, "briareus.command.replay-encryption.v1")
    ).decode("ascii")


def ledger_hmac_key(secret: str, subsystem: str) -> bytes:
    if subsystem not in {"runtime", "files", "native", "provider"}:
        raise ValueError("unsupported durable ledger key domain")
    return _derive(secret, f"briareus.ledger.{subsystem}.v1")


def login_bucket_key(secret: str) -> bytes:
    return _derive(secret, "briareus.identity.login-throttle.v1")
