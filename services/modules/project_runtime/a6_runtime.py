"""Private Briareus A9 signed RuntimeSession metadata consumer.

Every Backend effect is a fresh registered service+delegated User JWT pair,
a current Project/AgentSession SQL grant, full v2 payload SHA and one verified
C2 peer. A separately signed Ed25519 A9 lease JWS attests committed ledger
nonce+owner+CAS version, but NEVER authorizes OS processes or cleanup by itself.
No public route, fallback key, unsigned receipt or synthetic nonce exists here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .a9_signed_lease import (
    A9PinnedRuntimeKeyPort,
    A9SignedLeaseUntrusted,
    RuntimeLeaseReceipt,
    SignedRuntimeLeaseReceipt,
    verify_a9_signed_lease,
)
from .authorization import ProjectInvocation, ProjectPermit, ProjectRuntimeAuthority

A9RuntimeKind = Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
A9RuntimeAction = Literal[
    "files.write", "terminal.attach", "web.internal", "web.remote", "reverse.import"
]
A9RuntimeAudience = Literal["files", "terminal", "web", "reverse"]
_KIND_POLICY: dict[A9RuntimeKind, tuple[A9RuntimeAction, A9RuntimeAudience]] = {
    "files": ("files.write", "files"),
    "terminal": ("terminal.attach", "terminal"),
    "web_managed": ("web.internal", "web"),
    "web_remote": ("web.remote", "web"),
    "reverse": ("reverse.import", "reverse"),
}


class A6RuntimeUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RuntimeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_uuid: UUID

    @field_validator("operation_uuid")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if not isinstance(value, UUID) or value.version != 4:
            raise ValueError("A9 Runtime operation UUID must be v4")
        return value


class RuntimeOpenCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    instance_uuid: UUID
    kind: A9RuntimeKind
    idle_seconds: int = Field(ge=30, le=86400)
    hard_seconds: int = Field(ge=60, le=86400)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("runtime_session_uuid", "instance_uuid")
    @classmethod
    def _id(cls, value: UUID) -> UUID:
        if not isinstance(value, UUID) or value.version != 4:
            raise ValueError("A9 Runtime Session/instance UUID must be v4")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not value.isascii() or not value.isprintable():
            raise ValueError("A9 Runtime idempotency key invalid")
        return value


class RuntimeLeaseCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    expected_version: int = Field(ge=1)
    lease_nonce: UUID
    phase: Literal["heartbeat", "revoke", "lost", "cleanup", "close", "reconnect"]
    previous_instance_uuid: UUID | None = None

    @field_validator("runtime_session_uuid", "lease_nonce", "previous_instance_uuid")
    @classmethod
    def _id(cls, value: UUID | None) -> UUID | None:
        if value is not None and (not isinstance(value, UUID) or value.version != 4):
            raise ValueError("A9 Runtime lease identifier must be UUIDv4")
        return value


class RuntimeJobCommand(RuntimeCommand):
    runtime_session_uuid: UUID
    runtime_version: int = Field(ge=1)
    lease_nonce: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    hard_seconds: int = Field(ge=1, le=86400)


class RuntimeJobTransition(RuntimeCommand):
    runtime_session_uuid: UUID
    runtime_version: int = Field(ge=1)
    lease_nonce: UUID
    job_uuid: UUID
    expected_job_version: int = Field(ge=1)
    target: Literal["running", "succeeded", "failed", "unknown", "cancelled"]
    result_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RuntimeJobReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    job_uuid: UUID
    runtime_session_uuid: UUID
    project_id: UUID
    status: str
    revision: int = Field(ge=1)
    hard_expires_at: datetime


def runtime_payload_fingerprint(command: RuntimeCommand) -> str:
    """Field/byte-exact Backend A9 `project-runtime-v2` command digest."""
    return hashlib.sha256(
        json.dumps(
            {
                "protocol": "project-runtime-v2",
                "phase": type(command).__name__,
                "body": command.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class A6RuntimePeer:
    """Recipient service facts returned only by a real verified C2 peer port."""

    service_id: UUID
    instance_uuid: UUID
    target_audience: A9RuntimeAudience
    expires_at: datetime


class A6RuntimePeerPort(Protocol):
    async def verify_runtime_peer(self, evidence: object) -> A6RuntimePeer: ...


class A6SignedRuntimePort(Protocol):
    """Real Backend SignedRuntimeAuthority with two fresh JWTs per SQL UoW."""

    async def open(
        self,
        invocation: ProjectInvocation,
        *,
        command: RuntimeOpenCommand,
        fingerprint: str,
        peer: A6RuntimePeer,
    ) -> SignedRuntimeLeaseReceipt: ...

    async def transition(
        self,
        invocation: ProjectInvocation,
        *,
        command: RuntimeLeaseCommand,
        fingerprint: str,
        peer: A6RuntimePeer,
    ) -> SignedRuntimeLeaseReceipt: ...

    async def queue_job(
        self,
        invocation: ProjectInvocation,
        *,
        command: RuntimeJobCommand,
        fingerprint: str,
        peer: A6RuntimePeer,
    ) -> RuntimeJobReceipt: ...

    async def transition_job(
        self,
        invocation: ProjectInvocation,
        *,
        command: RuntimeJobTransition,
        fingerprint: str,
        peer: A6RuntimePeer,
    ) -> RuntimeJobReceipt: ...


class A6RuntimeSignedSource:
    """A9 JWS-verified DB intents; no OS process ownership or public mount."""

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        *,
        peer: A6RuntimePeerPort | None = None,
        backend: A6SignedRuntimePort | None = None,
        pinned_key: A9PinnedRuntimeKeyPort | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("A9 Runtime signed service timeout invalid")
        self.authority = authority
        self.peer = peer
        self.backend = backend
        self.pinned_key = pinned_key
        self.timeout_seconds = timeout_seconds

    async def _authorize(
        self,
        invocation: ProjectInvocation,
        *,
        action: A9RuntimeAction,
        expected_audience: A9RuntimeAudience,
        operation_uuid: UUID,
    ) -> tuple[ProjectPermit, A6RuntimePeer]:
        if (
            self.peer is None
            or self.backend is None
            or self.pinned_key is None
            or invocation.service_evidence is None
        ):
            raise A6RuntimeUnavailable("A9_SIGNED_RUNTIME_C2_TRUST_PORTS_REQUIRED")
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.request_uuid != operation_uuid
            or scope.action != action
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
        ):
            raise A6RuntimeUnavailable("A9_RUNTIME_REQUEST_SCOPE_INVALID")
        permit = await self.authority.require(invocation, action)
        if permit.project_access_revision is None:
            raise A6RuntimeUnavailable("A9_RUNTIME_PROJECT_REVISION_REQUIRED")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                peer = await self.peer.verify_runtime_peer(invocation.service_evidence)
        except Exception as exc:
            raise A6RuntimeUnavailable("A9_RUNTIME_PEER_UNAVAILABLE") from exc
        if (
            not isinstance(peer, A6RuntimePeer)
            or peer.target_audience != expected_audience
            or not isinstance(peer.service_id, UUID)
            or peer.service_id.version != 4
            or not isinstance(peer.instance_uuid, UUID)
            or peer.instance_uuid.version != 4
            or not isinstance(peer.expires_at, datetime)
            or peer.expires_at.tzinfo is None
            or peer.expires_at <= datetime.now(UTC)
        ):
            raise A6RuntimeUnavailable("A9_RUNTIME_PEER_INVALID")
        return permit, peer

    async def _verify_response(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        peer: A6RuntimePeer,
        kind: A9RuntimeKind,
        runtime_session_uuid: UUID,
        signed: SignedRuntimeLeaseReceipt,
    ) -> RuntimeLeaseReceipt:
        source = self.pinned_key
        if source is None:
            raise A6RuntimeUnavailable("A9_RUNTIME_ATTESTATION_KEY_UNAVAILABLE")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                public_key = await source.pinned_backend_lease_key(
                    expected_service_id=peer.service_id,
                    expected_instance_uuid=peer.instance_uuid,
                )
            receipt = verify_a9_signed_lease(
                signed,
                trusted_public_key=public_key,
                expected_service_id=peer.service_id,
                expected_instance_uuid=peer.instance_uuid,
                expected_audience=peer.target_audience,
                permit=permit,
                expected_runtime_session_uuid=runtime_session_uuid,
                expected_kind=kind,
            )
            if peer.expires_at <= datetime.now(UTC):
                raise A9SignedLeaseUntrusted("A9_LEASE_TRANSPORT_EXPIRED")
            if signed.attestation_expires_at > peer.expires_at:
                raise A9SignedLeaseUntrusted("A9_LEASE_EXCEEDS_VERIFIED_TRANSPORT")
        except Exception as exc:
            # A DB transaction may ALREADY have committed before the signed
            # receipt became unavailable. Never treat this as safe to retry.
            raise A6RuntimeUnavailable("A9_RUNTIME_ATTESTATION_UNVERIFIED_OUTCOME_UNKNOWN") from exc
        fresh = await self.authority.require(invocation, permit.action)
        if (
            fresh.actor_id != permit.actor_id
            or fresh.project_id != permit.project_id
            or fresh.session_uuid != permit.session_uuid
            or fresh.project_owner_scope != permit.project_owner_scope
            or fresh.project_owner_id != permit.project_owner_id
            or fresh.project_access_revision != permit.project_access_revision
            or fresh.decision_version != permit.decision_version
            or signed.attestation_expires_at <= datetime.now(UTC)
        ):
            raise A6RuntimeUnavailable("A9_RUNTIME_ACCESS_CHANGED_OUTCOME_UNKNOWN")
        return receipt

    async def open_intent(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A9RuntimeKind,
        runtime_session_uuid: UUID,
        operation_uuid: UUID,
        idle_seconds: int,
        hard_seconds: int,
    ) -> SignedRuntimeLeaseReceipt:
        """Return SIGNED DB metadata, never start Terminal/Chromium/Ghidra."""
        policy = _KIND_POLICY.get(kind)
        if policy is None:
            raise A6RuntimeUnavailable("A9_RUNTIME_KIND_INVALID")
        if (
            not isinstance(runtime_session_uuid, UUID)
            or runtime_session_uuid.version != 4
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or type(idle_seconds) is not int
            or type(hard_seconds) is not int
            or not 30 <= idle_seconds <= hard_seconds <= 86400
            or hard_seconds < 60
        ):
            raise A6RuntimeUnavailable("A9_RUNTIME_INTENT_INVALID")
        action, audience = policy
        permit, peer = await self._authorize(
            invocation,
            action=action,
            expected_audience=audience,
            operation_uuid=operation_uuid,
        )
        command = RuntimeOpenCommand(
            operation_uuid=operation_uuid,
            runtime_session_uuid=runtime_session_uuid,
            instance_uuid=peer.instance_uuid,
            kind=kind,
            idle_seconds=idle_seconds,
            hard_seconds=hard_seconds,
            idempotency_key=str(operation_uuid),
        )
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                signed = await self.backend.open(
                    invocation,
                    command=command,
                    fingerprint=runtime_payload_fingerprint(command),
                    peer=peer,
                )
        except Exception as exc:
            raise A6RuntimeUnavailable("A9_RUNTIME_OPEN_OUTCOME_UNKNOWN") from exc
        receipt = await self._verify_response(
            invocation,
            permit=permit,
            peer=peer,
            kind=kind,
            runtime_session_uuid=runtime_session_uuid,
            signed=signed,
        )
        if (
            receipt.state != "active"
            or receipt.owner_instance_uuid != peer.instance_uuid
            or receipt.cleanup_state != "not_needed"
            or receipt.lease_expires_at <= datetime.now(UTC)
        ):
            raise A6RuntimeUnavailable("A9_RUNTIME_OPEN_RESULT_UNKNOWN")
        return signed

    async def request_revoke_intent(
        self,
        invocation: ProjectInvocation,
        *,
        prior: SignedRuntimeLeaseReceipt,
        operation_uuid: UUID,
    ) -> SignedRuntimeLeaseReceipt:
        """Revoke signed SQL lease using the original A9 owner nonce + CAS.

        `prior` MUST be A9-verified and unexpired, not caller JSON. An old
        attestation cannot serve as indefinite custody or proof of OS stop.
        """
        if (
            not isinstance(prior, SignedRuntimeLeaseReceipt)
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
        ):
            raise A6RuntimeUnavailable("A9_RUNTIME_REVOKE_ORIGINAL_PROOF_REQUIRED")
        kind = prior.lease.kind
        action, audience = _KIND_POLICY[kind]
        permit, peer = await self._authorize(
            invocation,
            action=action,
            expected_audience=audience,
            operation_uuid=operation_uuid,
        )
        snapshot = await self._verify_response(
            invocation,
            permit=permit,
            peer=peer,
            kind=kind,
            runtime_session_uuid=prior.lease.runtime_session_uuid,
            signed=prior,
        )
        if snapshot.owner_instance_uuid != peer.instance_uuid:
            raise A6RuntimeUnavailable("A9_RUNTIME_REVOKE_REQUIRES_OWNER")
        command = RuntimeLeaseCommand(
            operation_uuid=operation_uuid,
            runtime_session_uuid=snapshot.runtime_session_uuid,
            expected_version=snapshot.revision,
            lease_nonce=snapshot.lease_nonce,
            phase="revoke",
        )
        assert self.backend is not None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.backend.transition(
                    invocation,
                    command=command,
                    fingerprint=runtime_payload_fingerprint(command),
                    peer=peer,
                )
        except Exception as exc:
            raise A6RuntimeUnavailable("A9_RUNTIME_REVOKE_OUTCOME_UNKNOWN") from exc
        renewed = await self._verify_response(
            invocation,
            permit=permit,
            peer=peer,
            kind=kind,
            runtime_session_uuid=snapshot.runtime_session_uuid,
            signed=result,
        )
        if (
            renewed.lease_nonce != snapshot.lease_nonce
            or renewed.owner_instance_uuid != snapshot.owner_instance_uuid
            or renewed.state not in {"revoked", "closed", "expired"}
            or renewed.revision not in {snapshot.revision, snapshot.revision + 1}
        ):
            raise A6RuntimeUnavailable("A9_RUNTIME_REVOKE_RECEIPT_INVALID")
        # This is a DB grant revocation, never a cgroup-kill or Chrome close.
        return result

    async def heartbeat_or_job(self, *_args: object, **_kwargs: object) -> None:
        # No approved OS attestor or signed status refresh source exists for
        # long-lived lease nonce custody, cgroup/fenced heartbeat and jobs.
        raise A6RuntimeUnavailable("A9_OS_RUNTIME_WORKER_CUSTODY_REQUIRED")
