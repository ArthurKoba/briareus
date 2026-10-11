"""Private Runtime owner lease/OS observation ABI, independent of owner SQL.

This module owns only immutable typed DTOs and Protocols. Caller fields do
not prove authorization: the recipient MUST verify fresh Identity/Control/
Access, pinned recipient/instance Ed25519, original Operation-UUID/key and
native OS cgroup/UID/mount witness. No SQL source, owner ledger or file bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from common.owner_contracts import (
    OwnerAuthorityUnavailable,
    OwnerCommandDTO,
    VerifiedOwnerServicePeer,
)

Kind = Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
_ALLOWED_KINDS: frozenset[str] = frozenset(
    {"files", "terminal", "web_managed", "web_remote", "reverse"}
)


@dataclass(frozen=True, slots=True)
class OwnerRuntimeLeaseClaim:
    runtime_session_uuid: UUID
    owner_service_id: UUID
    owner_instance: UUID
    project_id: UUID
    caller_user_id: UUID
    agent_session_uuid: UUID
    lease_nonce: UUID
    kind: Kind
    version: int
    lease_expires_at: datetime
    hard_expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedRuntimeStopped:
    runtime_session_uuid: UUID
    project_id: UUID
    previous_owner_service_id: UUID
    previous_instance_uuid: UUID
    lease_nonce: UUID
    observed_stopped_at: datetime
    native_scope_digest: str


class TrustedRuntimeCleanupVerifier(Protocol):
    def verify_stopped(
        self, evidence: object, *, supervisor_peer: VerifiedOwnerServicePeer
    ) -> VerifiedRuntimeStopped:
        """Must verify signed OS process/cgroup-owner evidence, not row status."""
        ...


@dataclass(frozen=True, slots=True)
class VerifiedRuntimeJobObservation:
    job_uuid: UUID
    runtime_session_uuid: UUID
    project_id: UUID
    owner_service_id: UUID
    owner_instance: UUID
    lease_nonce: UUID
    outcome: Literal["succeeded", "failed", "unknown"]
    result_sha256: str | None
    native_scope_digest: str
    observed_at: datetime


class TrustedRuntimeJobObserver(Protocol):
    def verify_job_effect(
        self, evidence: object, *, peer: VerifiedOwnerServicePeer
    ) -> VerifiedRuntimeJobObservation:
        """Only native OS process-owner proof can settle an external job."""
        ...


class TrustedOwnerRuntimeLeaseSigner(Protocol):
    def sign(self, claim: OwnerRuntimeLeaseClaim) -> str:
        """Produce verified-release Ed25519 JWS for a fenced owner lease."""
        ...


@dataclass(frozen=True, slots=True)
class RuntimeOwnerOriginalKey:
    """Private immutable lookup, NOT a bearer or an authorization decision.

    Inspect the ORIGINAL owner operation, never issue a replacement UUID after
    an unknown native effect. Bound to one actor/Project/AgentSession, one
    private recipient instance, and a fenced existing RuntimeSession lease.
    """

    operation_uuid: UUID
    idempotency_key: str
    caller_user_id: UUID
    project_id: UUID
    agent_session_uuid: UUID
    runtime_session_uuid: UUID
    service_id: UUID
    instance_uuid: UUID
    expected_lease_nonce: UUID
    expected_version: int
    source_command: OwnerCommandDTO

    def __post_init__(self) -> None:
        identities = (
            self.operation_uuid,
            self.caller_user_id,
            self.project_id,
            self.agent_session_uuid,
            self.runtime_session_uuid,
            self.service_id,
            self.instance_uuid,
            self.expected_lease_nonce,
        )
        if (
            any(type(value) is not UUID or value.version != 4 for value in identities)
            or self.idempotency_key != str(self.operation_uuid)
            or type(self.expected_version) is not int
            or self.expected_version < 1
            or not isinstance(self.source_command, OwnerCommandDTO)
            or self.source_command.target_owner != "runtime"
            or self.source_command.operation_uuid != self.operation_uuid
            or self.source_command.idempotency_key != self.idempotency_key
            or self.source_command.caller_user_id != self.caller_user_id
            or self.source_command.project_id != self.project_id
            or self.source_command.session_uuid != self.agent_session_uuid
        ):
            raise ValueError("Runtime owner original command/key/scope must be canonical")


def require_trusted_runtime_original_recipient(
    original: RuntimeOwnerOriginalKey, peer: VerifiedOwnerServicePeer
) -> None:
    """Deny stale/wrong mTLS or Unix recipient before private owner lookup."""
    if (
        not isinstance(original, RuntimeOwnerOriginalKey)
        or not isinstance(peer, VerifiedOwnerServicePeer)
        or peer.service_id != original.service_id
        or peer.instance_uuid != original.instance_uuid
        or peer.audience != "briareus:runtime"
        or peer.expires_at <= datetime.now(UTC)
    ):
        raise OwnerAuthorityUnavailable("Runtime original request recipient is not attested")


@dataclass(frozen=True, slots=True)
class UnverifiedRuntimeOwnerLeaseEnvelope:
    """Source response candidate; NEVER runtime permission or OS-effect proof."""

    original: RuntimeOwnerOriginalKey
    owner_jws: str
    observed_at: datetime

    def __post_init__(self) -> None:
        # Envelope construction is NOT a signature check. The consumer must
        # pin issuer/Ed25519 recipient+instance and use the actual JWS verifier,
        # then freshly authorize current Identity/Control/Access and OS.
        if (
            not isinstance(self.original, RuntimeOwnerOriginalKey)
            or not isinstance(self.owner_jws, str)
            or not 100 <= len(self.owner_jws) <= 8192
            or self.observed_at.tzinfo is None
            or self.observed_at > datetime.now(UTC)
        ):
            raise ValueError("unverified Runtime owner envelope is malformed")


class TrustedRuntimeOriginalLeasePort(Protocol):
    async def inspect_original(
        self,
        original: RuntimeOwnerOriginalKey,
        *,
        peer: VerifiedOwnerServicePeer,
    ) -> UnverifiedRuntimeOwnerLeaseEnvelope:
        """An actual C2 verifier must check transport, current owner SQL,
        original UUID/key, recipient, nonce, revision and bounds BEFORE
        fetching a source-signed lease. NO anonymous local fallback.
        """
        ...
