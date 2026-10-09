"""A6 private, typed signed-service operation transport (no public mount).

One authorization call requires an independently verified TLS/Unix-socket
peer, its Ed25519 service assertion, and a separately signed Backend
human-delegation. The canonical operation fingerprint binds all request
metadata and content hash to BOTH JWTs. Neither the request DTO nor the
returned receipt is a bearer authorization by itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_errors import AccessDenied, AuthenticationRequired, InvalidInput
from common.platform_ids import AgentSessionUuid, PlatformProjectId
from projects._runtime_ledger import RuntimeLease
from projects._runtime_persistence import RuntimeSessionRow

from ._runtime_lease_attestation import SignedRuntimeLeaseReceipt
from ._service_identity import (
    ACTION_AUDIENCES,
    AUTHORIZATION_AUDIENCE,
    SERVICE_LIFETIME,
    AuthorizedOperationReceipt,
    ServiceAuthorizationDecision,
    ServiceIdentityAuthority,
)

HexDigest = str


class ServiceOperationIntent(BaseModel):
    """Exact agreed A6 proof-issuance and authorization fingerprint input."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: UUID
    session_uuid: UUID
    instance_uuid: UUID
    operation: str = Field(min_length=1, max_length=128)
    target_audience: str = Field(min_length=1, max_length=64)
    resource_id: UUID | None = None
    operation_uuid: UUID
    payload_sha256: HexDigest = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("project_id", "session_uuid", "instance_uuid", "operation_uuid")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("signed operation IDs must be UUIDv4")
        return value

    @field_validator("resource_id")
    @classmethod
    def _resource_uuid(cls, value: UUID | None) -> UUID | None:
        if value is not None and value.version != 4:
            raise ValueError("resource ID must be UUIDv4")
        return value

    def fingerprint(self) -> str:
        if self.target_audience not in ACTION_AUDIENCES.get(self.operation, frozenset()):
            raise AccessDenied("service audience not permitted for action")
        # Stable language-neutral JSON: normalized keys, compact separators,
        # no user/operator bearer, source path, secret or arbitrary data.
        document = {
            "version": "project-operation-v1",
            **self.model_dump(mode="json", exclude_none=False),
        }
        return hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class ServiceAuthorizationHeaders(BaseModel):
    """Opaque private transport headers (must never be echoed/logged)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    service_assertion: SecretStr
    backend_delegation: SecretStr


class ServiceAuthorizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    intent: ServiceOperationIntent
    proof: ServiceAuthorizationHeaders


@dataclass(frozen=True, slots=True)
class VerifiedServicePeer:
    """Trusted adapter-produced TLS/Unix peer; not a caller-facing DTO."""

    service_id: UUID
    audience: str
    key_id: UUID
    instance_uuid: UUID
    expires_at: datetime
    transport: Literal["mtls", "unix-peer"]

    def __post_init__(self) -> None:
        if (
            self.service_id.version != 4
            or self.key_id.version != 4
            or self.instance_uuid.version != 4
            or self.expires_at.tzinfo is None
            or self.expires_at <= datetime.now(UTC)
            or self.transport not in {"mtls", "unix-peer"}
        ):
            raise AuthenticationRequired("trusted service transport peer invalid")


class TrustedServicePeerPort(Protocol):
    def verify_peer(self, evidence: object) -> VerifiedServicePeer:
        """Pure verification of a pre-attested connection's certificate/UID.

        Connection establishment and certificate/OS lookup occur outside the
        SQL transaction. Raw request headers never establish service identity.
        """
        ...


class PrivateServiceAuthorizationController:
    """Fail-closed service transport boundary; no fallback verifier available."""

    def __init__(
        self,
        authority: ServiceIdentityAuthority | None,
        peer_authenticator: TrustedServicePeerPort | None = None,
    ) -> None:
        self._authority = authority
        self._peer_authenticator = peer_authenticator

    async def consume_in_transaction(
        self,
        tx: AsyncSession,
        request: ServiceAuthorizeInput,
        *,
        peer_evidence: object,
    ) -> ServiceAuthorizationDecision:
        """Atomic signed request check inside the caller-owned ledger UoW."""
        if self._authority is None or self._peer_authenticator is None:
            raise AuthenticationRequired("C2 verified service transport unavailable")
        peer = self._peer_authenticator.verify_peer(peer_evidence)
        if not isinstance(peer, VerifiedServicePeer):
            raise AuthenticationRequired("C2 service transport identity invalid")
        intent = request.intent
        if peer.audience != intent.target_audience or peer.instance_uuid != intent.instance_uuid:
            raise AuthenticationRequired("service transport/audience mismatch")

        # No JTI is spent unless EVERY transport, signed JWT, user, Project,
        # Team and AgentSession check succeeds in this same transaction.
        decision = await self._authority.consume_service_operation(
            tx,
            service_assertion=request.proof.service_assertion.get_secret_value(),
            backend_delegation=request.proof.backend_delegation.get_secret_value(),
            expected_audience=intent.target_audience,
            expected_instance_uuid=peer.instance_uuid,
            expected_project_id=PlatformProjectId(intent.project_id),
            expected_session_uuid=AgentSessionUuid(intent.session_uuid),
            expected_action=intent.operation,
            expected_fingerprint=intent.fingerprint(),
            expected_resource_id=intent.resource_id,
        )
        if decision.service_id != peer.service_id or decision.service_key_id != peer.key_id:
            raise AuthenticationRequired("service JWT is not bound to current TLS/Unix peer")
        if decision.expires_at > peer.expires_at:
            # Transport can expire earlier than JWT; a returned receipt
            # may not survive its authenticated connection.
            raise AuthenticationRequired("transport identity expires before operation")
        return decision

    async def attest_runtime_lease(
        self,
        lease: RuntimeLease,
        decision: ServiceAuthorizationDecision,
    ) -> SignedRuntimeLeaseReceipt:
        """Only issue after committed ledger and fresh current grant/revision.

        The receipt's nonce/owner/version are loaded from PostgreSQL under
        lock AFTER service/User/Team/Project/AgentSession validation. Any
        intervening revoke/takeover/CAS change makes this proof unavailable.
        """
        if self._authority is None or self._peer_authenticator is None:
            raise AuthenticationRequired("C2 verified Runtime service transport unavailable")
        async with self._authority.app.db.transaction() as tx:
            await self._authority.verify_live_decision(tx, decision)
            row = await tx.scalar(
                select(RuntimeSessionRow)
                .where(RuntimeSessionRow.runtime_session_uuid == lease.runtime_session_uuid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                row is None
                or row.project_id != decision.project_id
                or row.agent_session_uuid != decision.session_uuid
                or row.actor_user_id != decision.actor_id
                or row.owner_service_id != decision.service_id
                or row.owner_instance != lease.owner_instance
                or row.lease_nonce != lease.lease_nonce
                or row.version != lease.version
                or row.status != lease.status
                or row.cleanup_state != lease.cleanup_state
                or row.hard_expires_at != lease.hard_expires_at
                or row.lease_expires_at != lease.lease_expires_at
            ):
                raise AccessDenied("Runtime lease changed before authoritative attestation")
            return self._authority.sign_verified_runtime_lease(lease, decision)

    async def authorize_project_operation(
        self,
        request: ServiceAuthorizeInput,
        *,
        peer_evidence: object,
    ) -> AuthorizedOperationReceipt:
        if self._authority is None:
            raise AuthenticationRequired("C2 verified service transport unavailable")
        async with self._authority.app.db.transaction() as tx:
            decision = await self.consume_in_transaction(tx, request, peer_evidence=peer_evidence)
            return AuthorizedOperationReceipt.from_verified(decision)


class ServiceAssertionSigner:
    """Source reference for runtime-owned Ed25519 private-key usage.

    Backend never provisions or stores the service private signing key. This
    helper can only sign an operation when a separate Backend delegation JTI
    and its exact signed metadata are already available to the runtime.
    """

    def __init__(
        self,
        *,
        private_key: Ed25519PrivateKey,
        key_id: UUID,
        service_id: UUID,
        instance_uuid: UUID,
        key_version: int,
        audience: str,
    ) -> None:
        if (
            key_id.version != 4
            or service_id.version != 4
            or instance_uuid.version != 4
            or key_version < 1
            or audience not in {a for group in ACTION_AUDIENCES.values() for a in group}
        ):
            raise InvalidInput("service signing identity configuration invalid")
        self._private_key = private_key
        self._key_id = key_id
        self._service_id = service_id
        self._instance_uuid = instance_uuid
        self._key_version = key_version
        self._audience = audience

    def sign(
        self,
        intent: ServiceOperationIntent,
        *,
        delegation_jti: UUID,
        correlation_id: UUID,
    ) -> SecretStr:
        if (
            intent.target_audience != self._audience
            or intent.instance_uuid != self._instance_uuid
            or delegation_jti.version != 4
            or correlation_id.version != 4
        ):
            raise AccessDenied("service/delegation operation scope mismatch")
        now = datetime.now(UTC)
        expires = now + SERVICE_LIFETIME
        payload = {
            "iss": f"service:{self._service_id}",
            "aud": AUTHORIZATION_AUDIENCE,
            "jti": str(uuid4()),
            "service_id": str(self._service_id),
            "instance_uuid": str(self._instance_uuid),
            "key_version": self._key_version,
            "target_audience": self._audience,
            "project_id": str(intent.project_id),
            "session_uuid": str(intent.session_uuid),
            "operation": intent.operation,
            "resource_id": str(intent.resource_id) if intent.resource_id else None,
            "delegation_jti": str(delegation_jti),
            "correlation_id": str(correlation_id),
            "request_fingerprint": intent.fingerprint(),
            "purpose": "authorize-project-operation",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires.timestamp()),
        }
        return SecretStr(
            jwt.encode(
                payload,
                self._private_key,
                algorithm="EdDSA",
                headers={"typ": "platform-service+jwt", "kid": str(self._key_id)},
            )
        )
