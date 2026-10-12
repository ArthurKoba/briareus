"""Compose trusted Rauthy identity, service peer and current Project membership.

No default implementation exists for the peer/Project authorities: only the
real upstream issuer, authenticated private transport and current Platform
owner can supply them. The HTTP request cannot assert trusted User/peer data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from fastapi import Request

from authorization._decision_api import (
    DecisionAuthenticationRequired,
    DecisionCommand,
    DecisionScopeDenied,
    VerifiedDecisionCaller,
)
from authorization._rauthy_jwks import RauthyJwksVerifier, RauthyTokenRejected


@dataclass(frozen=True, slots=True)
class VerifiedDecisionPeer:
    """Proof returned by an independently authenticated service transport."""

    consumer: Literal["gateway", "hand"]
    source_audience: str
    target_audience: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedProjectMembership:
    """Current Platform-owned Rauthy subject to internal User mapping."""

    rauthy_subject: str
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime


class TrustedDecisionPeerResolver(Protocol):
    async def verify_peer(self, request: Request) -> VerifiedDecisionPeer: ...


class CurrentProjectMembershipResolver(Protocol):
    async def current_member(
        self,
        *,
        rauthy_subject: str,
        project_uuid: UUID,
    ) -> VerifiedProjectMembership: ...


# Gateway admission is coarse-only. The verified Hand identity must match
# its actual effect family, regardless of bearer or posted action claims.
_HAND_AUDIENCE: dict[str, frozenset[str]] = {
    "files.read": frozenset({"files"}),
    "files.write": frozenset({"files"}),
    "terminal.execute": frozenset({"terminal"}),
    "web.access": frozenset({"web"}),
    "analysis.import": frozenset({"reverse"}),
    "integrations.use": frozenset({"svc", "infrastructure"}),
    "variables.use": frozenset({"svc", "infrastructure"}),
}


class RauthyDecisionAttestor:
    """Trust composition; never a policy engine or replacement for Cedar."""

    def __init__(
        self,
        *,
        bearer_verifier: RauthyJwksVerifier,
        peer_resolver: TrustedDecisionPeerResolver,
        membership_resolver: CurrentProjectMembershipResolver,
    ) -> None:
        self._bearer = bearer_verifier
        self._peer = peer_resolver
        self._membership = membership_resolver

    async def verify(self, request: Request, command: DecisionCommand) -> VerifiedDecisionCaller:
        if (
            len(request.headers.getlist("authorization")) != 1
            or request.headers.get("cookie") is not None
        ):
            raise DecisionAuthenticationRequired("one bearer and no browser cookie required")
        raw = request.headers.get("authorization", "")
        if not raw.startswith("Bearer ") or raw.count(" ") != 1:
            raise DecisionAuthenticationRequired("signed provider bearer required")
        try:
            signed = self._bearer.verify_access_token(raw[7:])
        except RauthyTokenRejected:
            raise DecisionAuthenticationRequired("provider bearer not verified") from None

        peer = await self._peer.verify_peer(request)
        now = datetime.now(UTC)
        if (
            not isinstance(peer, VerifiedDecisionPeer)
            or peer.target_audience != "briareus:access"
            or peer.expires_at.tzinfo is None
            or peer.expires_at <= now
            or (command.action == "mcp.connect" and peer.consumer != "gateway")
            or (command.action == "mcp.connect" and peer.source_audience != "gateway")
            or (
                command.action != "mcp.connect"
                and (
                    peer.consumer != "hand"
                    or peer.source_audience not in _HAND_AUDIENCE.get(command.action, frozenset())
                )
            )
        ):
            raise DecisionScopeDenied("verified service audience cannot perform action")

        membership = await self._membership.current_member(
            rauthy_subject=signed.subject,
            project_uuid=command.project_uuid,
        )
        if (
            not isinstance(membership, VerifiedProjectMembership)
            or membership.rauthy_subject != signed.subject
            or membership.project_uuid != command.project_uuid
            or membership.actor_uuid.version != 4
            or membership.expires_at.tzinfo is None
            or membership.expires_at <= now
        ):
            raise DecisionScopeDenied("no current verified Project membership")
        expires_at = min(peer.expires_at, signed.expires_at, membership.expires_at)
        if expires_at <= now:
            raise DecisionAuthenticationRequired("trust proof expired")
        return VerifiedDecisionCaller(
            actor_uuid=membership.actor_uuid,
            project_uuid=command.project_uuid,
            agent_session_uuid=command.agent_session_uuid,
            consumer=peer.consumer,
            authority="rauthy",
            verified_peer_audience=peer.target_audience,
            proof_expires_at=expires_at,
        )
