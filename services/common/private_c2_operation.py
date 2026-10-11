"""Private owner command admission across independently signed C2 authorities.

This module contains NO cross-owner SQL, no HTTP route, no signing key,
no token minting, no native effect. A real connector must supply current
Identity User/JTI, registered Access service one-use assertion, pinned
Identity/Control/Access source proofs and current owner revocation ports.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from common.owner_contracts import (
    CurrentOwnerAuthorityPort,
    OwnerAuthorityUnavailable,
    OwnerCommandDTO,
    OwnerProofAuthority,
    SignedOwnerProofs,
    TrustedOwnerServicePeerPort,
    VerifiedOwnerOperation,
    VerifiedOwnerServicePeer,
    require_online_owner_decision,
)
from common.private_user_token import PrivateUserTokenClaims


@dataclass(frozen=True, slots=True)
class VerifiedOneUseServiceAssertion:
    """C2/access SQL-consumed assertion, not a caller-provided JWT payload."""

    service_id: UUID
    instance_uuid: UUID
    registered_service_key_id: UUID
    assertion_jti: UUID
    delegation_jti: UUID
    recipient_audience: str
    actor_user_id: UUID
    project_id: UUID
    agent_session_uuid: UUID
    operation_uuid: UUID
    operation: str
    payload_sha256: str
    expires_at: datetime

    def __post_init__(self) -> None:
        ids = (
            self.service_id,
            self.instance_uuid,
            self.registered_service_key_id,
            self.assertion_jti,
            self.delegation_jti,
            self.actor_user_id,
            self.project_id,
            self.agent_session_uuid,
            self.operation_uuid,
        )
        if (
            any(not isinstance(x, UUID) or x.version != 4 for x in ids)
            or not self.recipient_audience.startswith("briareus:")
            or not self.operation
            or len(self.operation) > 128
            or len(self.payload_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.payload_sha256)
            or self.expires_at.tzinfo is None
            or self.expires_at <= datetime.now(UTC)
            or self.expires_at - datetime.now(UTC) > timedelta(seconds=30)
        ):
            raise OwnerAuthorityUnavailable("service assertion original binding invalid")


class TrustedCurrentUserBearerPort(Protocol):
    async def require_current(
        self, *, bearer: SecretStr, recipient: VerifiedOwnerServicePeer
    ) -> PrivateUserTokenClaims:
        """Verify pinned Ed25519 JWT + CURRENT Identity User/version/JTI.

        This port must NOT decode unsigned claims, trust a browser-provided
        subject, or reuse an expired admission from another request. Real
        service-peer evidence is independently verified before this call.
        """
        ...


class TrustedOnceServiceAssertionPort(Protocol):
    async def consume_registered_once(
        self,
        *,
        request: OwnerCommandDTO,
        recipient: VerifiedOwnerServicePeer,
        human: PrivateUserTokenClaims,
    ) -> VerifiedOneUseServiceAssertion:
        """Consume registered service Ed25519 JTI once in its Access DB UoW.

        Bind service key/instance, original operation, current human bearer
        JTI and source Project/AgentSession to the same request fingerprint.
        Header/cookie/JWKS claims alone never authorize a service identity.
        """
        ...


@dataclass(frozen=True, slots=True)
class VerifiedPrivateOperationAdmission:
    """A fresh scoped SOURCE decision; no native OS effect or global commit."""

    decision: VerifiedOwnerOperation
    recipient: VerifiedOwnerServicePeer
    service_assertion_jti: UUID
    verified_at: datetime


class PrivateCurrentOwnerCommandGate:
    """Actual three-owner signature/source freshness composition, no DB join."""

    def __init__(
        self,
        *,
        peers: TrustedOwnerServicePeerPort,
        assertions: TrustedOnceServiceAssertionPort,
        humans: TrustedCurrentUserBearerPort,
        authority: OwnerProofAuthority,
        current_owners: CurrentOwnerAuthorityPort,
        pinned_identity_issuer: str,
        pinned_user_audience: str,
    ) -> None:
        if any(x is None for x in (peers, assertions, humans, authority, current_owners)):
            raise ValueError("all pinned source/peer/Access/JTI authorities required")
        if not pinned_identity_issuer or not pinned_user_audience:
            raise ValueError("private owner admission requires pinned signed User issuer/audience")
        self.user_issuer = pinned_identity_issuer
        self.user_audience = pinned_user_audience
        self.peers = peers
        self.assertions = assertions
        self.humans = humans
        self.authority = authority
        self.current_owners = current_owners

    async def require_current(
        self,
        *,
        command: OwnerCommandDTO,
        signed: SignedOwnerProofs,
        human_bearer: SecretStr,
        peer_evidence: object,
    ) -> VerifiedPrivateOperationAdmission:
        if (
            not isinstance(command, OwnerCommandDTO)
            or not isinstance(signed, SignedOwnerProofs)
            or not isinstance(human_bearer, SecretStr)
            or not 40 <= len(human_bearer.get_secret_value()) <= 8192
            or command.idempotency_key != str(command.operation_uuid)
            or command.session_uuid.version != 4
            or command.project_id.version != 4
        ):
            raise OwnerAuthorityUnavailable("original owner source/bearer not trusted")
        try:
            peer = self.peers.verify_peer(peer_evidence)
            if (
                not isinstance(peer, VerifiedOwnerServicePeer)
                or peer.expires_at <= datetime.now(UTC)
                or peer.audience != f"briareus:{command.target_owner}"
            ):
                raise OwnerAuthorityUnavailable("private original recipient is not attested")
            async with asyncio.timeout(3):
                human = await self.humans.require_current(bearer=human_bearer, recipient=peer)
            now = int(datetime.now(UTC).timestamp())
            if (
                not isinstance(human, PrivateUserTokenClaims)
                or human.iss != self.user_issuer
                or human.aud != self.user_audience
                or human.purpose != "briareus-panel-user-v1"
                or human.sub.version != 4
                or human.jti.version != 4
                or not human.iat <= human.nbf <= now < human.exp
                or human.exp - human.iat > 900
                or human.sub != command.caller_user_id
                or human.credential_version != command.expected_identity_revision
            ):
                raise OwnerAuthorityUnavailable("unverified or revoked current User JTI")
            verified = self.authority.require_current(command, signed)
            async with asyncio.timeout(3):
                fresh = await require_online_owner_decision(
                    self.authority, self.current_owners, command
                )
            if (
                verified.identity_epoch != fresh.identity_epoch
                or verified.control_epoch != fresh.control_epoch
                or verified.access_epoch != fresh.access_epoch
                or verified.actor_role != fresh.actor_role
                or verified.request != command
            ):
                raise OwnerAuthorityUnavailable("owner source epochs changed during admission")
            # One-use registered Access service assertion is consumed only
            # AFTER all available owner signatures and fresh permissions.
            async with asyncio.timeout(3):
                issued = await self.assertions.consume_registered_once(
                    request=command, recipient=peer, human=human
                )
            if (
                not isinstance(issued, VerifiedOneUseServiceAssertion)
                or issued.service_id != peer.service_id
                or issued.instance_uuid != peer.instance_uuid
                or issued.recipient_audience != peer.audience
                or issued.actor_user_id != command.caller_user_id
                or issued.project_id != command.project_id
                or issued.agent_session_uuid != command.session_uuid
                or issued.operation_uuid != command.operation_uuid
                or issued.operation != command.operation
                or issued.payload_sha256 != command.payload_sha256
                or issued.expires_at > peer.expires_at
            ):
                raise OwnerAuthorityUnavailable("service assertion not bound to original source")
            async with asyncio.timeout(3):
                # Owner scope can change while Access commits the assertion;
                # recheck right AFTER consumption. If revoked, fail closed,
                # leaving JTI spent without ever dispatching an effect.
                latest = await require_online_owner_decision(
                    self.authority, self.current_owners, command
                )
            if (
                latest.identity_epoch != fresh.identity_epoch
                or latest.control_epoch != fresh.control_epoch
                or latest.access_epoch != fresh.access_epoch
                or latest.actor_role != fresh.actor_role
                or issued.expires_at <= datetime.now(UTC)
            ):
                raise OwnerAuthorityUnavailable("owner or service JTI expired after Access commit")
            return VerifiedPrivateOperationAdmission(
                decision=latest,
                recipient=peer,
                service_assertion_jti=issued.assertion_jti,
                verified_at=datetime.now(UTC),
            )
        except Exception:
            raise OwnerAuthorityUnavailable(
                "current private C2 source authorization denied"
            ) from None
