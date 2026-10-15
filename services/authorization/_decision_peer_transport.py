"""Transport-authenticated Gateway/Hand proof for independent Cedar decisions.

The ASGI scope extension is produced ONLY by a real authenticated private
mTLS/Unix peer adapter. No HTTP header, URL, body or bearer may create it.
It binds service identity, immutable resolved effect, exact HTTP JSON bytes
and a consumed one-shot nonce to the current request.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from fastapi import Request

from authorization._action_audiences import ALLOWED_AUDIENCES
from authorization._decision_api import (
    DecisionAuthenticationRequired,
    DecisionAuthorityUnavailable,
    DecisionScopeDenied,
)
from authorization._rauthy_decision_attestor import VerifiedDecisionPeer

_SCOPE_KEY = "briareus.verified_private_peer.v1"
_MAX_BODY = 8192
_NONCE_PATTERN = re.compile(r"[a-f0-9]{32,64}\Z", re.ASCII)
_HEX_DIGEST = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class VerifiedTransportPeerRequest:
    """Authenticated, request-bound fact set from TLS/Unix service supervisor.

    Only trusted server-side code may instantiate and place this in ASGI
    scope after independently validating peer certificate/OS identity and
    the Hand's owner-resolved effect tuple. A claimed header is invalid.
    """

    transport: Literal["mtls", "unix-peer"]
    consumer: Literal["gateway", "hand"]
    source_audience: str
    target_audience: Literal["briareus:access"]
    http_body_sha256: str
    resolved_effect_key: str | None
    nonce: str
    authenticated_at: datetime
    expires_at: datetime
    verified_peer: bool


class TrustedPeerReplayGuard(Protocol):
    async def consume(self, *, source_audience: str, nonce: str, body_sha256: str) -> bool:
        """Atomically consume a request nonce in a shared reliable store.

        False on replay; raised exception or unavailable store denies.
        Implementation must be usable across all Authorization replicas.
        """
        ...


class TransportAuthenticatedDecisionPeerResolver:
    """Fail-closed mTLS/Unix scope proof + digest/nonce verification.

    This is NOT an HTTP credential validator or mTLS server. TLS/Unix
    termination must be independent and already installed by the service
    operator. Without both that attestor and replay guard this returns 503.
    """

    def __init__(self, *, replay_guard: TrustedPeerReplayGuard) -> None:
        if replay_guard is None:
            raise ValueError("real private peer replay authority is required")
        self._replay = replay_guard

    async def verify_peer(self, request: Request) -> VerifiedDecisionPeer:
        supplied = request.scope.get(_SCOPE_KEY)
        if supplied is None:
            raise DecisionAuthorityUnavailable("private peer transport unavailable")
        if not isinstance(supplied, VerifiedTransportPeerRequest):
            raise DecisionAuthenticationRequired("no independently verified private peer")
        now = datetime.now(UTC)
        if (
            supplied.verified_peer is not True
            or supplied.transport not in {"mtls", "unix-peer"}
            or supplied.consumer not in {"gateway", "hand"}
            or supplied.source_audience not in ALLOWED_AUDIENCES
            or supplied.target_audience != "briareus:access"
            or (supplied.consumer == "gateway" and supplied.source_audience != "gateway")
            or (supplied.consumer == "hand" and supplied.source_audience == "gateway")
            or (supplied.consumer == "gateway" and supplied.resolved_effect_key is not None)
            or (supplied.consumer == "hand" and not supplied.resolved_effect_key)
            or not isinstance(supplied.http_body_sha256, str)
            or _HEX_DIGEST.fullmatch(supplied.http_body_sha256) is None
            or not isinstance(supplied.nonce, str)
            or _NONCE_PATTERN.fullmatch(supplied.nonce) is None
            or not isinstance(supplied.authenticated_at, datetime)
            or not isinstance(supplied.expires_at, datetime)
            or supplied.authenticated_at.tzinfo is None
            or supplied.expires_at.tzinfo is None
            or supplied.authenticated_at > now + timedelta(seconds=2)
            or supplied.authenticated_at < now - timedelta(seconds=15)
            or not now < supplied.expires_at <= supplied.authenticated_at + timedelta(seconds=15)
        ):
            raise DecisionScopeDenied("private service peer scope or freshness denied")
        # The certificate-bound source audience must own the exact Hand
        # namespace being asserted. A Files peer cannot request a Web tool.
        if supplied.consumer == "hand":
            try:
                effect = json.loads(supplied.resolved_effect_key or "")
            except (ValueError, TypeError):
                raise DecisionScopeDenied("invalid private Hand effect selector") from None
            if (
                not isinstance(effect, list)
                or len(effect) != 4
                or any(not isinstance(value, str) for value in effect)
                or effect[0] != supplied.source_audience
                or supplied.resolved_effect_key
                != json.dumps(effect, ensure_ascii=True, separators=(",", ":"))
            ):
                raise DecisionScopeDenied("authenticated Hand does not own effect")
        body = await request.body()
        if (
            len(body) == 0
            or len(body) > _MAX_BODY
            or hashlib.sha256(body).hexdigest() != supplied.http_body_sha256
        ):
            raise DecisionScopeDenied("peer proof is not bound to actual request body")
        try:
            consumed = await self._replay.consume(
                source_audience=supplied.source_audience,
                nonce=supplied.nonce,
                body_sha256=supplied.http_body_sha256,
            )
        except Exception:
            raise DecisionAuthorityUnavailable("peer replay authority unavailable") from None
        if consumed is not True:
            raise DecisionScopeDenied("private service proof already consumed")
        return VerifiedDecisionPeer(
            consumer=supplied.consumer,
            source_audience=supplied.source_audience,
            target_audience=supplied.target_audience,
            expires_at=supplied.expires_at,
            attested_effect_key=supplied.resolved_effect_key,
        )
