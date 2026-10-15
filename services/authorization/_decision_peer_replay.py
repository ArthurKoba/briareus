"""Distributed, atomic, one-shot private service-peer attestation nonces.

The Valkey client is injected by a protected owner service startup, never
created from a caller's URI, bearer, request header or untrusted ENV. No
fallback to process-local replay caches or best-effort grants is permitted.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

from authorization._decision_api import DecisionAuthorityUnavailable

_NAMESPACE = "briareus:access:verified-peer:v1"
_KEY_FRAGMENT = re.compile(r"[a-f0-9]{32,64}\Z", re.ASCII)
_HEX_SHA = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)


class PrivateValkeyNoncePort(Protocol):
    async def set(self, name: str, value: str, *, nx: bool, ex: int) -> object: ...


class ValkeyPeerReplayGuard:
    """Shared 30s NX barrier; atomically burns a given peer nonce once.

    This protects all Authorization replicas when each uses the same
    protected Valkey and namespace. Expiry is strictly bounded to avoid
    stale state buildup. SQL/Cedar still check the current grant every call.
    """

    def __init__(self, *, valkey: PrivateValkeyNoncePort) -> None:
        if valkey is None:
            raise ValueError("approved distributed private Valkey transport required")
        self._valkey = valkey

    async def consume(self, *, source_audience: str, nonce: str, body_sha256: str) -> bool:
        if (
            not isinstance(source_audience, str)
            or source_audience
            not in {
                "gateway",
                "files",
                "terminal",
                "web",
                "svc",
                "reverse",
                "infrastructure",
            }
            or not isinstance(nonce, str)
            or _KEY_FRAGMENT.fullmatch(nonce) is None
            or not isinstance(body_sha256, str)
            or _HEX_SHA.fullmatch(body_sha256) is None
        ):
            return False
        # Do not persist token, actor ID, credential, body or URL in Valkey.
        key_digest = hashlib.sha256(f"{source_audience}:{nonce}".encode("ascii")).hexdigest()
        cache_key = f"{_NAMESPACE}:{key_digest}"
        try:
            reserved = await self._valkey.set(cache_key, body_sha256, nx=True, ex=30)
        except Exception:
            raise DecisionAuthorityUnavailable("private peer nonce authority unavailable") from None
        if reserved is True or reserved in ("OK", b"OK"):
            return True
        if reserved is None or reserved is False:
            return False
        # Unexpected provider response must not become a Permit.
        raise DecisionAuthorityUnavailable("private peer nonce result invalid")
