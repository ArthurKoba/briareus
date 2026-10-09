"""Accepted Backend A5 RuntimeSession/Job ledger consumer, unmounted.

Source: projects/_runtime_ledger.py. SQL RuntimeSession `owner_instance`,
`lease_nonce`, `version` and `lease_expires_at` are independent of local worker
PID/context. A DB state is not proof that an OS job or Chrome has stopped.
Every call delegates signed service+User authorization to a trusted Backend
port inside a fresh UoW; never accept a caller-made non-secret receipt as auth.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from .authorization import ProjectAction, ProjectInvocation, ProjectPermit, ProjectRuntimeAuthority

A5RuntimeKind = Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
A5RuntimeState = Literal["active", "lost", "revoked", "expired", "closed"]
A5CleanupState = Literal["not_needed", "pending", "confirmed", "failed", "unknown"]
A5JobState = Literal["queued", "running", "succeeded", "failed", "unknown", "cancelled"]


class A5RuntimeUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class A5RuntimeLease:
    """Exact A5 `RuntimeLedger.RuntimeLease` source record, no OS PID."""

    runtime_session_uuid: UUID
    project_id: UUID
    agent_session_uuid: UUID
    actor_user_id: UUID
    kind: A5RuntimeKind
    owner_instance: UUID
    lease_nonce: UUID
    status: A5RuntimeState
    version: int
    idle_expires_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime
    cleanup_state: A5CleanupState


@dataclass(frozen=True, slots=True)
class A5RuntimeJob:
    """Exact A5 `RuntimeJob` source projection; outcome not process liveness."""

    job_uuid: UUID
    runtime_session_uuid: UUID
    project_id: UUID
    status: A5JobState
    version: int
    hard_expires_at: datetime


@dataclass(frozen=True, slots=True)
class A5ExternalCleanupEvidence:
    """Trusted separately owned cleanup ACK, NOT a self-declared status."""

    project_id: UUID
    runtime_session_uuid: UUID
    agent_session_uuid: UUID
    actor_id: UUID
    owner_instance: UUID
    lease_nonce: UUID
    kind: A5RuntimeKind
    native_or_os_cleanup_confirmed: bool
    confirmed_at: datetime


class A5DomainCleanupVerifier(Protocol):
    async def verify_external_cleanup(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime: A5RuntimeLease,
    ) -> A5ExternalCleanupEvidence: ...


@dataclass(frozen=True, slots=True)
class A5JobExecutionEvidence:
    """Independent OS/worker proof; never a caller-filled job status."""

    project_id: UUID
    agent_session_uuid: UUID
    actor_id: UUID
    runtime_session_uuid: UUID
    job_uuid: UUID
    owner_instance: UUID
    lease_nonce: UUID
    kind: A5RuntimeKind
    target: Literal["running", "succeeded", "failed"]
    result_digest: str | None
    isolated_worker_verified: bool
    process_tree_hard_ttl_verified: bool
    confirmed_at: datetime


class A5JobExecutionVerifier(Protocol):
    async def verify_worker_transition(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime: A5RuntimeLease,
        job: A5RuntimeJob,
        target: Literal["running", "succeeded", "failed"],
    ) -> A5JobExecutionEvidence: ...


class A5TrustedRuntimeLedgerPort(Protocol):
    """Owner-private A5 SQL port; requires HMAC-sealed live service decision."""

    async def open(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        kind: A5RuntimeKind,
        instance: UUID,
        idle_seconds: int,
        hard_seconds: int,
        idempotency_key: str,
    ) -> A5RuntimeLease: ...

    async def inspect_open(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        kind: A5RuntimeKind,
        idempotency_key: str,
    ) -> A5RuntimeLease | None: ...

    async def heartbeat(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        expected_version: int,
        lease_nonce: UUID,
        instance: UUID,
    ) -> A5RuntimeLease: ...

    async def revoke(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        expected_version: int,
    ) -> A5RuntimeLease: ...

    async def mark_lost(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        expected_version: int,
    ) -> A5RuntimeLease: ...

    async def confirm_cleanup(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        expected_version: int,
        owner_instance: UUID,
        lease_nonce: UUID,
    ) -> A5RuntimeLease: ...

    async def reconnect(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        expected_version: int,
        new_instance: UUID,
    ) -> A5RuntimeLease: ...

    async def close(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        expected_version: int,
    ) -> A5RuntimeLease: ...

    async def queue_job(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        runtime_version: int,
        lease_nonce: UUID,
        owner_instance: UUID,
        idempotency_key: str,
        request_fingerprint: str,
        hard_seconds: int,
    ) -> A5RuntimeJob: ...

    async def transition_job(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        job_uuid: UUID,
        runtime_version: int,
        expected_job_version: int,
        lease_nonce: UUID,
        owner_instance: UUID,
        target: A5JobState,
        result_digest: str | None = None,
    ) -> A5RuntimeJob: ...

    async def inspect_job(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        idempotency_key: str,
    ) -> A5RuntimeJob | None: ...


_KIND_ACTION: dict[A5RuntimeKind, ProjectAction] = {
    "files": "files.write",
    "terminal": "terminal.attach",
    "web_managed": "web.internal",
    "web_remote": "web.remote",
    "reverse": "reverse.import",
}


class A5RuntimeLedgerClient:
    """Read/command source projection with per-call A5 grant and CAS checks."""

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        ledger: A5TrustedRuntimeLedgerPort | None = None,
        *,
        owner_instance_uuid: UUID,
        cleanup_verifier: A5DomainCleanupVerifier | None = None,
        job_verifier: A5JobExecutionVerifier | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isinstance(owner_instance_uuid, UUID) or owner_instance_uuid.version != 4:
            raise ValueError("A5 runtime owner instance must be UUIDv4")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("A5 runtime timeout invalid")
        self.authority = authority
        self.ledger = ledger
        self.cleanup_verifier = cleanup_verifier
        self.job_verifier = job_verifier
        self.owner_instance_uuid = owner_instance_uuid
        self.timeout_seconds = timeout_seconds

    async def _permit(self, invocation: ProjectInvocation, kind: A5RuntimeKind) -> ProjectPermit:
        operation = _KIND_ACTION.get(kind)
        if operation is None:
            raise A5RuntimeUnavailable("A5_RUNTIME_KIND_UNKNOWN")
        return await self.authority.require(invocation, operation)

    def _lease(
        self,
        record: A5RuntimeLease,
        permit: ProjectPermit,
        kind: A5RuntimeKind,
        *,
        owner_instance: UUID | None = None,
        require_active: bool = False,
    ) -> A5RuntimeLease:
        if (
            not isinstance(record, A5RuntimeLease)
            or record.project_id != permit.project_id
            or record.agent_session_uuid != permit.session_uuid
            or record.actor_user_id != permit.actor_id
            or record.kind != kind
            or not isinstance(record.runtime_session_uuid, UUID)
            or record.runtime_session_uuid.version != 4
            or not isinstance(record.owner_instance, UUID)
            or record.owner_instance.version != 4
            or (owner_instance is not None and record.owner_instance != owner_instance)
            or not isinstance(record.lease_nonce, UUID)
            or record.lease_nonce.version != 4
            or type(record.version) is not int
            or record.version < 1
            or record.status not in {"active", "lost", "revoked", "expired", "closed"}
            or record.cleanup_state
            not in {"not_needed", "pending", "confirmed", "failed", "unknown"}
            or not all(
                isinstance(x, datetime) and x.tzinfo is not None
                for x in (record.idle_expires_at, record.hard_expires_at, record.lease_expires_at)
            )
            or record.lease_expires_at > record.hard_expires_at
            or record.idle_expires_at > record.hard_expires_at
            or (
                require_active
                and (
                    record.status != "active"
                    or min(record.idle_expires_at, record.hard_expires_at, record.lease_expires_at)
                    <= datetime.now(UTC)
                )
            )
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_LEDGER_INVALID")
        return record

    async def open_intent(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        idle_seconds: int,
        hard_seconds: int,
        operation_uuid: UUID,
    ) -> A5RuntimeLease:
        """A durable DB intent, not a spawned process or browser context."""
        if self.ledger is None:
            raise A5RuntimeUnavailable("A5_RUNTIME_LEDGER_UNAVAILABLE")
        if (
            not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or type(idle_seconds) is not int
            or not 30 <= idle_seconds <= 86400
            or type(hard_seconds) is not int
            or not 60 <= hard_seconds <= 86400
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_OPEN_INVALID")
        permit = await self._permit(invocation, kind)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                record = await self.ledger.open(
                    invocation,
                    permit=permit,
                    kind=kind,
                    instance=self.owner_instance_uuid,
                    idle_seconds=idle_seconds,
                    hard_seconds=hard_seconds,
                    idempotency_key=str(operation_uuid),
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_RUNTIME_OPEN_OUTCOME_UNKNOWN") from exc
        return self._lease(
            record, permit, kind, owner_instance=self.owner_instance_uuid, require_active=True
        )

    async def inspect_open(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        operation_uuid: UUID,
    ) -> A5RuntimeLease | None:
        if (
            self.ledger is None
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_INSPECTION_UNAVAILABLE")
        permit = await self._permit(invocation, kind)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                record = await self.ledger.inspect_open(
                    invocation,
                    permit=permit,
                    kind=kind,
                    idempotency_key=str(operation_uuid),
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_RUNTIME_INSPECTION_UNAVAILABLE") from exc
        return None if record is None else self._lease(record, permit, kind)

    async def heartbeat(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        before: A5RuntimeLease,
    ) -> A5RuntimeLease:
        if self.ledger is None:
            raise A5RuntimeUnavailable("A5_RUNTIME_LEDGER_UNAVAILABLE")
        permit = await self._permit(invocation, kind)
        self._lease(
            before, permit, kind, owner_instance=self.owner_instance_uuid, require_active=True
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                after = await self.ledger.heartbeat(
                    invocation,
                    permit=permit,
                    runtime_uuid=before.runtime_session_uuid,
                    expected_version=before.version,
                    lease_nonce=before.lease_nonce,
                    instance=self.owner_instance_uuid,
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_RUNTIME_HEARTBEAT_OUTCOME_UNKNOWN") from exc
        self._lease(
            after, permit, kind, owner_instance=self.owner_instance_uuid, require_active=True
        )
        if (
            after.runtime_session_uuid != before.runtime_session_uuid
            or after.lease_nonce != before.lease_nonce
            or after.version != before.version + 1
            or after.hard_expires_at != before.hard_expires_at
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_CAS_INVALID")
        return after

    async def _change(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        before: A5RuntimeLease,
        operation: Literal["revoke", "mark_lost", "close"],
    ) -> A5RuntimeLease:
        if self.ledger is None:
            raise A5RuntimeUnavailable("A5_RUNTIME_LEDGER_UNAVAILABLE")
        permit = await self._permit(invocation, kind)
        self._lease(before, permit, kind)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                if operation == "revoke":
                    after = await self.ledger.revoke(
                        invocation,
                        permit=permit,
                        runtime_uuid=before.runtime_session_uuid,
                        expected_version=before.version,
                    )
                elif operation == "mark_lost":
                    after = await self.ledger.mark_lost(
                        invocation,
                        permit=permit,
                        runtime_uuid=before.runtime_session_uuid,
                        expected_version=before.version,
                    )
                else:
                    after = await self.ledger.close(
                        invocation,
                        permit=permit,
                        runtime_uuid=before.runtime_session_uuid,
                        expected_version=before.version,
                    )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_RUNTIME_TRANSITION_OUTCOME_UNKNOWN") from exc
        self._lease(after, permit, kind)
        if (
            after.runtime_session_uuid != before.runtime_session_uuid
            or after.agent_session_uuid != before.agent_session_uuid
            or after.hard_expires_at != before.hard_expires_at
            or after.version not in {before.version, before.version + 1}
            or (operation == "revoke" and after.status != "revoked")
            or (operation == "mark_lost" and after.status != "lost")
            or (
                operation == "close"
                and (after.status != "closed" or after.cleanup_state != "confirmed")
            )
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_TRANSITION_INVALID")
        return after

    async def revoke(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        before: A5RuntimeLease,
    ) -> A5RuntimeLease:
        """DB revocation requests cleanup; does not kill OS/browser."""
        return await self._change(invocation, kind=kind, before=before, operation="revoke")

    async def mark_lost(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        before: A5RuntimeLease,
    ) -> A5RuntimeLease:
        """The A5 backend verifies lease_expires_at before marking lost."""
        return await self._change(invocation, kind=kind, before=before, operation="mark_lost")

    async def close(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        before: A5RuntimeLease,
    ) -> A5RuntimeLease:
        """Only a previously OS/Chrome-confirmed cleanup can close ledger."""
        if before.cleanup_state != "confirmed":
            raise A5RuntimeUnavailable("A5_RUNTIME_CLEANUP_UNCONFIRMED")
        return await self._change(invocation, kind=kind, before=before, operation="close")

    async def confirm_cleanup(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        before: A5RuntimeLease,
    ) -> A5RuntimeLease:
        if self.ledger is None or self.cleanup_verifier is None:
            raise A5RuntimeUnavailable("A5_RUNTIME_CLEANUP_OWNER_UNAVAILABLE")
        permit = await self._permit(invocation, kind)
        self._lease(before, permit, kind)
        if before.status not in {"lost", "expired", "revoked", "closed"}:
            raise A5RuntimeUnavailable("A5_RUNTIME_CLEANUP_NOT_REQUIRED")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                proof = await self.cleanup_verifier.verify_external_cleanup(
                    invocation,
                    permit=permit,
                    runtime=before,
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_RUNTIME_CLEANUP_EVIDENCE_MISSING") from exc
        if (
            not isinstance(proof, A5ExternalCleanupEvidence)
            or proof.project_id != permit.project_id
            or proof.actor_id != permit.actor_id
            or proof.agent_session_uuid != permit.session_uuid
            or proof.runtime_session_uuid != before.runtime_session_uuid
            or proof.owner_instance != before.owner_instance
            or proof.lease_nonce != before.lease_nonce
            or proof.kind != kind
            or proof.native_or_os_cleanup_confirmed is not True
            or not isinstance(proof.confirmed_at, datetime)
            or proof.confirmed_at.tzinfo is None
            or not datetime.now(UTC) - timedelta(seconds=60)
            <= proof.confirmed_at
            <= datetime.now(UTC)
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_CLEANUP_EVIDENCE_INVALID")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.ledger.confirm_cleanup(
                    invocation,
                    permit=permit,
                    runtime_uuid=before.runtime_session_uuid,
                    expected_version=before.version,
                    owner_instance=before.owner_instance,
                    lease_nonce=before.lease_nonce,
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_RUNTIME_CLEANUP_ACK_UNKNOWN") from exc
        self._lease(result, permit, kind)
        if (
            result.runtime_session_uuid != before.runtime_session_uuid
            or result.cleanup_state != "confirmed"
            or result.hard_expires_at != before.hard_expires_at
            or result.lease_nonce != before.lease_nonce
            or result.owner_instance != before.owner_instance
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_CLEANUP_ACK_INVALID")
        return result

    async def reconnect_intent(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        before: A5RuntimeLease,
    ) -> A5RuntimeLease:
        """Metadata-only reconnect after cleanup; NEVER replay OS actions."""
        if self.ledger is None:
            raise A5RuntimeUnavailable("A5_RUNTIME_LEDGER_UNAVAILABLE")
        permit = await self._permit(invocation, kind)
        self._lease(before, permit, kind)
        if before.status != "lost" or before.cleanup_state != "confirmed":
            raise A5RuntimeUnavailable("A5_RUNTIME_RECONNECT_REQUIRES_CLEANUP")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.ledger.reconnect(
                    invocation,
                    permit=permit,
                    runtime_uuid=before.runtime_session_uuid,
                    expected_version=before.version,
                    new_instance=self.owner_instance_uuid,
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_RUNTIME_RECONNECT_OUTCOME_UNKNOWN") from exc
        self._lease(
            result, permit, kind, owner_instance=self.owner_instance_uuid, require_active=True
        )
        if (
            result.runtime_session_uuid != before.runtime_session_uuid
            or result.hard_expires_at != before.hard_expires_at
            or result.version != before.version + 1
            or result.lease_nonce == before.lease_nonce
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_RECONNECT_INVALID")
        return result

    @staticmethod
    def _job(
        record: A5RuntimeJob,
        permit: ProjectPermit,
        runtime_uuid: UUID,
        *,
        expected_state: A5JobState | None = None,
    ) -> A5RuntimeJob:
        if (
            not isinstance(record, A5RuntimeJob)
            or record.project_id != permit.project_id
            or record.runtime_session_uuid != runtime_uuid
            or not isinstance(record.job_uuid, UUID)
            or record.job_uuid.version != 4
            or type(record.version) is not int
            or record.version < 1
            or record.status
            not in {"queued", "running", "succeeded", "failed", "unknown", "cancelled"}
            or (expected_state is not None and record.status != expected_state)
            or not isinstance(record.hard_expires_at, datetime)
            or record.hard_expires_at.tzinfo is None
        ):
            raise A5RuntimeUnavailable("A5_RUNTIME_JOB_RECORD_INVALID")
        return record

    async def queue_job_intent(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        runtime: A5RuntimeLease,
        operation_uuid: UUID,
        request_fingerprint: str,
        hard_seconds: int,
    ) -> A5RuntimeJob:
        """Durable queued intent: does not start Terminal/Ghidra OS action."""
        if self.ledger is None:
            raise A5RuntimeUnavailable("A5_JOB_LEDGER_UNAVAILABLE")
        if (
            not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or not isinstance(request_fingerprint, str)
            or len(request_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in request_fingerprint)
            or type(hard_seconds) is not int
            or not 1 <= hard_seconds <= 86400
        ):
            raise A5RuntimeUnavailable("A5_JOB_INTENT_INVALID")
        permit = await self._permit(invocation, kind)
        self._lease(
            runtime, permit, kind, owner_instance=self.owner_instance_uuid, require_active=True
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.ledger.queue_job(
                    invocation,
                    permit=permit,
                    runtime_uuid=runtime.runtime_session_uuid,
                    runtime_version=runtime.version,
                    lease_nonce=runtime.lease_nonce,
                    owner_instance=self.owner_instance_uuid,
                    idempotency_key=str(operation_uuid),
                    request_fingerprint=request_fingerprint,
                    hard_seconds=hard_seconds,
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_JOB_QUEUE_OUTCOME_UNKNOWN") from exc
        return self._job(result, permit, runtime.runtime_session_uuid, expected_state="queued")

    async def transition_job_intent(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        runtime: A5RuntimeLease,
        job: A5RuntimeJob,
        target: A5JobState,
        result_digest: str | None = None,
    ) -> A5RuntimeJob:
        """CAS ledger only. A completed DB job is not OS process evidence."""
        if self.ledger is None:
            raise A5RuntimeUnavailable("A5_JOB_LEDGER_UNAVAILABLE")
        permit = await self._permit(invocation, kind)
        self._lease(runtime, permit, kind, owner_instance=self.owner_instance_uuid)
        self._job(job, permit, runtime.runtime_session_uuid)
        if target not in {"running", "succeeded", "failed", "unknown", "cancelled"}:
            raise A5RuntimeUnavailable("A5_JOB_TRANSITION_INVALID")
        if target == "succeeded" and (
            not isinstance(result_digest, str)
            or len(result_digest) != 64
            or any(c not in "0123456789abcdef" for c in result_digest)
        ):
            raise A5RuntimeUnavailable("A5_JOB_RESULT_DIGEST_REQUIRED")
        if target != "succeeded" and result_digest is not None:
            raise A5RuntimeUnavailable("A5_JOB_RESULT_DIGEST_NOT_ALLOWED")
        if (target in {"running", "cancelled"} and job.status != "queued") or (
            target in {"succeeded", "failed", "unknown"} and job.status != "running"
        ):
            raise A5RuntimeUnavailable("A5_JOB_STATUS_TRANSITION_UNSAFE")
        if target in {"running", "succeeded", "failed"}:
            # The preceding finite set check narrows target at runtime;
            # Python type narrowing for set membership needs an explicit cast.
            worker_target = cast(Literal["running", "succeeded", "failed"], target)
            verifier = self.job_verifier
            if verifier is None:
                raise A5RuntimeUnavailable("A5_OS_JOB_SUPERVISOR_UNAVAILABLE")
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    evidence = await verifier.verify_worker_transition(
                        invocation,
                        permit=permit,
                        runtime=runtime,
                        job=job,
                        target=worker_target,
                    )
            except Exception as exc:
                raise A5RuntimeUnavailable("A5_JOB_WORKER_EVIDENCE_UNAVAILABLE") from exc
            if (
                not isinstance(evidence, A5JobExecutionEvidence)
                or evidence.project_id != permit.project_id
                or evidence.agent_session_uuid != permit.session_uuid
                or evidence.actor_id != permit.actor_id
                or evidence.runtime_session_uuid != runtime.runtime_session_uuid
                or evidence.job_uuid != job.job_uuid
                or evidence.owner_instance != runtime.owner_instance
                or evidence.lease_nonce != runtime.lease_nonce
                or evidence.kind != kind
                or evidence.target != target
                or evidence.result_digest != result_digest
                or evidence.isolated_worker_verified is not True
                or evidence.process_tree_hard_ttl_verified is not True
                or not isinstance(evidence.confirmed_at, datetime)
                or evidence.confirmed_at.tzinfo is None
                or not datetime.now(UTC) - timedelta(seconds=60)
                <= evidence.confirmed_at
                <= datetime.now(UTC)
            ):
                raise A5RuntimeUnavailable("A5_JOB_WORKER_EVIDENCE_INVALID")
            # Refresh the actual User+service+Project/AgentSession grant after
            # OS evidence and immediately before durable SQL job CAS.
            renewed = await self._permit(invocation, kind)
            if (
                renewed.actor_id != permit.actor_id
                or renewed.project_access_revision != permit.project_access_revision
                or renewed.decision_version != permit.decision_version
                or renewed.project_owner_id != permit.project_owner_id
                or renewed.project_owner_scope != permit.project_owner_scope
            ):
                raise A5RuntimeUnavailable("A5_JOB_ACCESS_STALE")
            permit = renewed
        try:
            async with asyncio.timeout(self.timeout_seconds):
                after = await self.ledger.transition_job(
                    invocation,
                    permit=permit,
                    runtime_uuid=runtime.runtime_session_uuid,
                    job_uuid=job.job_uuid,
                    runtime_version=runtime.version,
                    expected_job_version=job.version,
                    lease_nonce=runtime.lease_nonce,
                    owner_instance=self.owner_instance_uuid,
                    target=target,
                    result_digest=result_digest,
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_JOB_TRANSITION_OUTCOME_UNKNOWN") from exc
        self._job(after, permit, runtime.runtime_session_uuid, expected_state=target)
        if after.job_uuid != job.job_uuid or after.version != job.version + 1:
            raise A5RuntimeUnavailable("A5_JOB_CAS_INVALID")
        return after

    async def inspect_job(
        self,
        invocation: ProjectInvocation,
        *,
        kind: A5RuntimeKind,
        runtime_uuid: UUID,
        operation_uuid: UUID,
    ) -> A5RuntimeJob | None:
        if (
            self.ledger is None
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
        ):
            raise A5RuntimeUnavailable("A5_JOB_LEDGER_UNAVAILABLE")
        permit = await self._permit(invocation, kind)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                record = await self.ledger.inspect_job(
                    invocation,
                    permit=permit,
                    runtime_uuid=runtime_uuid,
                    idempotency_key=str(operation_uuid),
                )
        except Exception as exc:
            raise A5RuntimeUnavailable("A5_JOB_INSPECTION_UNAVAILABLE") from exc
        if record is None:
            return None
        if (
            not isinstance(record, A5RuntimeJob)
            or record.runtime_session_uuid != runtime_uuid
            or record.project_id != permit.project_id
            or record.status
            not in {"queued", "running", "succeeded", "failed", "unknown", "cancelled"}
            or type(record.version) is not int
            or record.version < 1
            or not isinstance(record.job_uuid, UUID)
            or record.job_uuid.version != 4
        ):
            raise A5RuntimeUnavailable("A5_JOB_METADATA_INVALID")
        return record
