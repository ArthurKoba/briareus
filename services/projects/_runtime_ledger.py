"""Transactional Project runtime leases and job outcomes.

A durable lease is evidence of DB ownership, never evidence that an OS process,
browser or Ghidra worker has stopped. External process cleanup requires a
trusted, separately authenticated Runtime consumer and a confirmed ACK.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._service_identity import (
    CurrentServiceDecisionValidator,
    ServiceAuthorizationDecision,
)
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from common.platform_ids import PlatformProjectId

from ._runtime_persistence import RuntimeJobRow, RuntimeSessionRow

KIND_ACTION = {
    "files": ("files", "files.write"),
    "terminal": ("terminal", "terminal.execute"),
    "web_managed": ("web", "web.access"),
    "web_remote": ("web", "web.access"),
    "reverse": ("reverse", "analysis.import"),
}
LEASE_TTL = timedelta(seconds=30)
MIN_IDLE = timedelta(seconds=30)
MAX_IDLE = timedelta(hours=24)
MAX_HARD = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(UTC)


def _fingerprint(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise InvalidInput("request fingerprint must be canonical SHA-256")


@dataclass(frozen=True, slots=True)
class RuntimeLease:
    runtime_session_uuid: UUID
    project_id: PlatformProjectId
    agent_session_uuid: UUID
    actor_user_id: UUID
    kind: str
    owner_instance: UUID
    lease_nonce: UUID
    status: str
    version: int
    idle_expires_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime
    cleanup_state: str


@dataclass(frozen=True, slots=True)
class RuntimeJob:
    job_uuid: UUID
    runtime_session_uuid: UUID
    project_id: PlatformProjectId
    status: str
    version: int
    hard_expires_at: datetime


def _lease(row: RuntimeSessionRow) -> RuntimeLease:
    return RuntimeLease(
        runtime_session_uuid=row.runtime_session_uuid,
        project_id=PlatformProjectId(row.project_id),
        agent_session_uuid=row.agent_session_uuid,
        actor_user_id=row.actor_user_id,
        kind=row.kind,
        owner_instance=row.owner_instance,
        lease_nonce=row.lease_nonce,
        status=row.status,
        version=row.version,
        idle_expires_at=row.idle_expires_at,
        hard_expires_at=row.hard_expires_at,
        lease_expires_at=row.lease_expires_at,
        cleanup_state=row.cleanup_state,
    )


def _job(row: RuntimeJobRow) -> RuntimeJob:
    return RuntimeJob(
        job_uuid=row.job_uuid,
        runtime_session_uuid=row.runtime_session_uuid,
        project_id=PlatformProjectId(row.project_id),
        status=row.status,
        version=row.version,
        hard_expires_at=row.hard_expires_at,
    )


class RuntimeLeaseConflict(Conflict):
    code = "runtime_lease_conflict"


@dataclass(frozen=True, slots=True)
class RuntimeCleanupEvidence:
    runtime_session_uuid: UUID
    project_id: PlatformProjectId
    owner_service_id: UUID
    previous_instance_uuid: UUID
    lease_nonce: UUID
    observed_stopped_at: datetime


class TrustedRuntimeCleanupObserver(Protocol):
    def verify_stopped(
        self,
        *,
        decision: ServiceAuthorizationDecision,
        runtime_session_uuid: UUID,
        previous_instance_uuid: UUID,
        lease_nonce: UUID,
    ) -> RuntimeCleanupEvidence:
        """Pure verification of signed supervisor evidence, no I/O in SQL UoW.

        Obtain independent cgroup/process/browser-disconnect observation BEFORE
        invoking Backend. This port must not make OS/network requests itself.
        """
        ...


class RuntimeLedger:
    def __init__(
        self,
        app: PlatformApplication,
        *,
        signing_key: bytes,
        validator: CurrentServiceDecisionValidator | None = None,
        cleanup_observer: TrustedRuntimeCleanupObserver | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("runtime idempotency HMAC key too short")
        self.app = app
        self.validator = validator
        self.cleanup_observer = cleanup_observer
        self._key = signing_key

    def _digest(self, key: str) -> str:
        if not 1 <= len(key) <= 128 or not key.isascii() or not key.isprintable():
            raise InvalidInput("runtime command requires bounded Idempotency-Key")
        return hmac.new(self._key, key.encode(), hashlib.sha256).hexdigest()

    async def _authorize(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        kind: str,
        project_id: PlatformProjectId,
    ) -> None:
        policy = KIND_ACTION.get(kind)
        if (
            policy is None
            or decision.audience != policy[0]
            or decision.operation != policy[1]
            or decision.project_id != project_id
            or decision.expires_at <= _now()
        ):
            raise AccessDenied("runtime action requires verified service and grant")
        if self.validator is None:
            raise AccessDenied("C2 service identity validator is not configured")
        await self.validator.verify_live_decision(tx, decision)

    @staticmethod
    def _instance(instance: UUID) -> UUID:
        if not isinstance(instance, UUID) or instance.version != 4:
            raise InvalidInput("runtime instance must be a UUIDv4")
        return instance

    async def _owned(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        expected_version: int,
        nonce: UUID | None = None,
        instance: UUID | None = None,
        allow_recovery: bool = False,
    ) -> RuntimeSessionRow:
        if runtime_uuid.version != 4:
            raise AccessDenied("runtime_session_uuid must be UUIDv4")
        query = select(RuntimeSessionRow).where(
            RuntimeSessionRow.runtime_session_uuid == runtime_uuid
        )
        probe = cast(RuntimeSessionRow | None, await tx.scalar(query))
        if probe is None:
            raise AccessDenied("runtime session not found in selected Project")
        await self._authorize(tx, decision, probe.kind, PlatformProjectId(probe.project_id))
        row = cast(
            RuntimeSessionRow | None,
            await tx.scalar(query.with_for_update().execution_options(populate_existing=True)),
        )
        if row is None:
            raise AccessDenied("runtime session disappeared during authorization")
        if (
            row.agent_session_uuid != decision.session_uuid
            or row.actor_user_id != decision.actor_id
            or row.owner_service_id != decision.service_id
            or (not allow_recovery and row.owner_instance != decision.instance_uuid)
            or row.version != expected_version
            or (nonce is not None and row.lease_nonce != nonce)
            or (instance is not None and row.owner_instance != instance)
        ):
            raise RuntimeLeaseConflict("runtime session owner or revision changed")
        return row

    async def open(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        *,
        kind: str,
        instance: UUID,
        runtime_session_uuid: UUID,
        idle_seconds: int,
        hard_seconds: int,
        idempotency_key: str,
    ) -> RuntimeLease:
        await self._authorize(tx, decision, kind, decision.project_id)
        instance = self._instance(instance)
        if not isinstance(runtime_session_uuid, UUID) or runtime_session_uuid.version != 4:
            raise InvalidInput("RuntimeSession UUID must be stable UUIDv4")
        if decision.instance_uuid != instance:
            raise AccessDenied("signed service instance does not own runtime")
        if not (30 <= idle_seconds <= 86400 and 60 <= hard_seconds <= 86400):
            raise InvalidInput("runtime idle/hard TTL outside allowed bounds")
        # A retry after network uncertainty returns the SAME lease record,
        # never starts a second owner/native process. Lock the existing
        # Project row to serialize the missing-row check between workers.
        digest = self._digest(idempotency_key)
        fingerprint = hashlib.sha256(
            json.dumps(
                [kind, str(instance), str(runtime_session_uuid), idle_seconds, hard_seconds],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        project = await self.app.projects.get(tx, decision.project_id, lock=True)
        if project is None:
            raise AccessDenied("Runtime Project unavailable")
        previous = cast(
            RuntimeSessionRow | None,
            await tx.scalar(
                select(RuntimeSessionRow)
                .where(
                    RuntimeSessionRow.project_id == decision.project_id,
                    RuntimeSessionRow.owner_service_id == decision.service_id,
                    RuntimeSessionRow.actor_user_id == decision.actor_id,
                    RuntimeSessionRow.agent_session_uuid == decision.session_uuid,
                    RuntimeSessionRow.kind == kind,
                    RuntimeSessionRow.open_idempotency_digest == digest,
                )
                .with_for_update()
            ),
        )
        if previous is not None:
            if (
                previous.open_request_fingerprint != fingerprint
                or previous.runtime_session_uuid != runtime_session_uuid
            ):
                raise Conflict("RuntimeSession open key reused with another request")
            return _lease(previous)
        now = _now()
        hard = min(
            now + timedelta(seconds=hard_seconds),
            decision.agent_session_hard_expires_at,
        )
        if hard <= now + timedelta(seconds=5):
            raise AccessDenied("AgentSession hard TTL too short for runtime lease")
        row = RuntimeSessionRow(
            runtime_session_uuid=runtime_session_uuid,
            project_id=decision.project_id,
            agent_session_uuid=decision.session_uuid,
            actor_user_id=decision.actor_id,
            kind=kind,
            owner_service_id=decision.service_id,
            owner_instance=instance,
            open_idempotency_digest=digest,
            open_request_fingerprint=fingerprint,
            lease_nonce=uuid4(),
            version=1,
            status="active",
            cleanup_state="not_needed",
            idle_ttl_seconds=idle_seconds,
            created_at=now,
            last_heartbeat_at=now,
            idle_expires_at=min(now + timedelta(seconds=idle_seconds), hard),
            hard_expires_at=hard,
            lease_expires_at=min(now + LEASE_TTL, hard),
        )
        tx.add(row)
        await tx.flush()
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="runtime.session_opened",
            target=row.runtime_session_uuid,
            event={
                "service_id": str(decision.service_id),
                "kind": kind,
                "runtime_revision": row.version,
            },
        )
        return _lease(row)

    async def heartbeat(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        expected_version: int,
        lease_nonce: UUID,
        instance: UUID,
    ) -> RuntimeLease:
        row = await self._owned(
            tx,
            decision,
            runtime_uuid,
            expected_version=expected_version,
            nonce=lease_nonce,
            instance=self._instance(instance),
        )
        now = _now()
        if (
            row.status != "active"
            or row.lease_expires_at <= now
            or row.idle_expires_at <= now
            or row.hard_expires_at <= now
        ):
            raise RuntimeLeaseConflict("runtime lease expired or requires recovery")
        row.version += 1
        row.last_heartbeat_at = now
        row.lease_expires_at = min(now + LEASE_TTL, row.hard_expires_at)
        row.idle_expires_at = min(
            now + timedelta(seconds=row.idle_ttl_seconds), row.hard_expires_at
        )
        return _lease(row)

    async def revoke(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        expected_version: int,
    ) -> RuntimeLease:
        row = await self._owned(tx, decision, runtime_uuid, expected_version=expected_version)
        if row.status in {"closed", "revoked", "expired"}:
            return _lease(row)
        row.status = "revoked"
        row.cleanup_state = "pending"
        row.version += 1
        row.ended_at = _now()
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="runtime.session_revoked",
            target=row.runtime_session_uuid,
            event={"runtime_revision": row.version, "cleanup_required": True},
        )
        return _lease(row)

    async def mark_lost(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        expected_version: int,
    ) -> RuntimeLease:
        row = await self._owned(tx, decision, runtime_uuid, expected_version=expected_version)
        if row.status != "active" or row.lease_expires_at > _now():
            raise RuntimeLeaseConflict("runtime owner lease is not lost")
        row.status = "lost"
        row.cleanup_state = "pending"
        row.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="runtime.session_lost",
            target=runtime_uuid,
            event={"runtime_revision": row.version, "cleanup_required": True},
        )
        return _lease(row)

    async def confirm_cleanup(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        expected_version: int,
        owner_instance: UUID,
        lease_nonce: UUID,
    ) -> RuntimeLease:
        """Private trusted OS worker confirms stop; never inferred from DB TTL."""
        if self.cleanup_observer is None:
            raise AccessDenied("C2 trusted OS cleanup supervisor is not configured")
        row = await self._owned(
            tx,
            decision,
            runtime_uuid,
            expected_version=expected_version,
            nonce=lease_nonce,
            instance=self._instance(owner_instance),
            allow_recovery=True,
        )
        evidence = self.cleanup_observer.verify_stopped(
            decision=decision,
            runtime_session_uuid=runtime_uuid,
            previous_instance_uuid=owner_instance,
            lease_nonce=lease_nonce,
        )
        if (
            not isinstance(evidence, RuntimeCleanupEvidence)
            or evidence.runtime_session_uuid != runtime_uuid
            or evidence.project_id != decision.project_id
            or evidence.owner_service_id != decision.service_id
            or evidence.previous_instance_uuid != owner_instance
            or evidence.lease_nonce != lease_nonce
            or evidence.observed_stopped_at.tzinfo is None
            or evidence.observed_stopped_at > _now()
        ):
            raise AccessDenied("verified OS cleanup evidence missing or mismatched")
        if row.status not in {"lost", "expired", "revoked", "closed"}:
            raise RuntimeLeaseConflict("cleanup confirmation requires stopped runtime state")
        if row.cleanup_state not in {"pending", "unknown", "confirmed"}:
            raise RuntimeLeaseConflict("no cleanup obligation exists")
        if row.cleanup_state == "confirmed":
            return _lease(row)
        row.cleanup_state = "confirmed"
        row.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="runtime.cleanup_confirmed",
            target=runtime_uuid,
            event={"runtime_revision": row.version, "owner_instance": owner_instance},
        )
        return _lease(row)

    async def reconnect(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        expected_version: int,
        new_instance: UUID,
    ) -> RuntimeLease:
        """Reconnect only after trusted cleanup ACK; never adopt a live process."""
        if self._instance(new_instance) != decision.instance_uuid:
            raise AccessDenied("replacement instance is not current signed peer")
        row = await self._owned(
            tx,
            decision,
            runtime_uuid,
            expected_version=expected_version,
            allow_recovery=True,
        )
        now = _now()
        if (
            row.owner_instance == new_instance
            or row.status != "lost"
            or row.cleanup_state != "confirmed"
            or row.hard_expires_at <= now + timedelta(seconds=5)
        ):
            raise RuntimeLeaseConflict("runtime cannot be safely reconnected")
        row.owner_instance = self._instance(new_instance)
        row.lease_nonce = uuid4()
        row.status = "active"
        row.cleanup_state = "not_needed"
        row.version += 1
        row.last_heartbeat_at = now
        row.lease_expires_at = min(now + LEASE_TTL, row.hard_expires_at)
        row.idle_expires_at = min(
            now + timedelta(seconds=row.idle_ttl_seconds),
            row.hard_expires_at,
        )
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="runtime.session_reconnected",
            target=runtime_uuid,
            event={"runtime_revision": row.version, "owner_instance": row.owner_instance},
        )
        return _lease(row)

    async def close(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        expected_version: int,
    ) -> RuntimeLease:
        # Cleanup is attested by a different healthy instance after the
        # original owner has stopped. It is safe to close an already stopped
        # row with the same verified Project/actor/service and expected CAS.
        row = await self._owned(
            tx,
            decision,
            runtime_uuid,
            expected_version=expected_version,
            allow_recovery=True,
        )
        if row.status not in {"lost", "expired", "revoked", "closed"}:
            raise RuntimeLeaseConflict("active runtime cannot be marked closed")
        if row.cleanup_state != "confirmed":
            raise RuntimeLeaseConflict("runtime shutdown must be confirmed before close")
        if row.status != "closed":
            row.status = "closed"
            row.ended_at = _now()
            row.version += 1
            self.app._audit(
                tx,
                actor=decision.actor_id,
                project=decision.project_id,
                action="runtime.session_closed",
                target=runtime_uuid,
                event={"runtime_revision": row.version},
            )
        return _lease(row)

    async def expire_batch(
        self,
        tx: AsyncSession,
        *,
        limit: int = 64,
    ) -> int:
        """Trusted backend-only TTL sweep; emits cleanup, never kills processes."""
        if not 1 <= limit <= 256:
            raise InvalidInput("runtime expiry batch limit outside allowed range")
        now = _now()
        rows = await tx.scalars(
            select(RuntimeSessionRow)
            .where(
                or_(
                    and_(
                        RuntimeSessionRow.status == "active",
                        or_(
                            RuntimeSessionRow.hard_expires_at <= now,
                            RuntimeSessionRow.idle_expires_at <= now,
                            RuntimeSessionRow.lease_expires_at <= now,
                        ),
                    ),
                    and_(
                        RuntimeSessionRow.status == "lost",
                        or_(
                            RuntimeSessionRow.hard_expires_at <= now,
                            RuntimeSessionRow.idle_expires_at <= now,
                        ),
                    ),
                ),
            )
            .order_by(RuntimeSessionRow.hard_expires_at, RuntimeSessionRow.runtime_session_uuid)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        count = 0
        for row in rows:
            row.status = (
                "expired" if row.hard_expires_at <= now or row.idle_expires_at <= now else "lost"
            )
            row.cleanup_state = "pending"
            row.ended_at = now
            row.version += 1
            self.app._audit(
                tx,
                actor=None,
                project=PlatformProjectId(row.project_id),
                action=(
                    "runtime.session_expired" if row.status == "expired" else "runtime.session_lost"
                ),
                target=row.runtime_session_uuid,
                event={
                    "runtime_revision": row.version,
                    "cleanup_required": True,
                    "owner_service_id": str(row.owner_service_id),
                },
            )
            count += 1
        return count

    async def queue_job(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        runtime_version: int,
        lease_nonce: UUID,
        owner_instance: UUID,
        idempotency_key: str,
        request_fingerprint: str,
        hard_seconds: int,
    ) -> RuntimeJob:
        """One queued job per runtime session + idempotency key.

        An unknown or running previous job never becomes another process.
        """
        _fingerprint(request_fingerprint)
        row = await self._owned(
            tx,
            decision,
            runtime_uuid,
            expected_version=runtime_version,
            nonce=lease_nonce,
            instance=self._instance(owner_instance),
        )
        now = _now()
        if (
            row.status != "active"
            or row.lease_expires_at <= now
            or row.idle_expires_at <= now
            or row.hard_expires_at <= now
        ):
            raise RuntimeLeaseConflict("runtime lease cannot accept new jobs")
        if not 1 <= hard_seconds <= 86400:
            raise InvalidInput("job hard TTL outside allowed bounds")
        digest = self._digest(idempotency_key)
        prior = cast(
            RuntimeJobRow | None,
            await tx.scalar(
                select(RuntimeJobRow)
                .where(
                    RuntimeJobRow.project_id == decision.project_id,
                    RuntimeJobRow.runtime_session_uuid == runtime_uuid,
                    RuntimeJobRow.idempotency_digest == digest,
                )
                .with_for_update()
            ),
        )
        if prior is not None:
            if (
                prior.request_fingerprint != request_fingerprint
                or prior.operation != decision.operation
                or prior.actor_user_id != decision.actor_id
                or prior.agent_session_uuid != decision.session_uuid
            ):
                raise Conflict("job idempotency key reused with another request")
            return _job(prior)
        other_unknown = await tx.scalar(
            select(RuntimeJobRow.job_uuid)
            .where(
                RuntimeJobRow.runtime_session_uuid == runtime_uuid,
                RuntimeJobRow.request_fingerprint == request_fingerprint,
                RuntimeJobRow.status.in_(("queued", "running", "unknown")),
            )
            .limit(1)
        )
        if other_unknown is not None:
            raise RuntimeLeaseConflict("same external job outcome is unconfirmed; reconcile first")
        hard = min(
            row.hard_expires_at,
            now + timedelta(seconds=hard_seconds),
        )
        job = RuntimeJobRow(
            job_uuid=uuid4(),
            runtime_session_uuid=runtime_uuid,
            project_id=decision.project_id,
            owner_service_id=decision.service_id,
            actor_user_id=decision.actor_id,
            agent_session_uuid=decision.session_uuid,
            idempotency_digest=digest,
            request_fingerprint=request_fingerprint,
            operation=decision.operation,
            status="queued",
            version=1,
            hard_expires_at=hard,
        )
        tx.add(job)
        await tx.flush()
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action="runtime.job_queued",
            target=job.job_uuid,
            event={"runtime_session_uuid": str(runtime_uuid)},
        )
        return _job(job)

    async def transition_job(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        job_uuid: UUID,
        *,
        runtime_version: int,
        expected_job_version: int,
        lease_nonce: UUID,
        owner_instance: UUID,
        target: str,
        result_digest: str | None = None,
    ) -> RuntimeJob:
        """Job CAS: queued->running; running->result/unknown; never re-run unknown."""
        row = await self._owned(
            tx,
            decision,
            runtime_uuid,
            expected_version=runtime_version,
            nonce=lease_nonce,
            instance=self._instance(owner_instance),
        )
        job = cast(
            RuntimeJobRow | None,
            await tx.scalar(
                select(RuntimeJobRow)
                .where(
                    RuntimeJobRow.job_uuid == job_uuid,
                    RuntimeJobRow.runtime_session_uuid == runtime_uuid,
                    RuntimeJobRow.project_id == decision.project_id,
                )
                .with_for_update()
            ),
        )
        if (
            job is None
            or job.owner_service_id != decision.service_id
            or job.actor_user_id != decision.actor_id
            or job.agent_session_uuid != decision.session_uuid
            or job.operation != decision.operation
            or job.version != expected_job_version
        ):
            raise RuntimeLeaseConflict("runtime job revision/owner mismatch")
        now = _now()
        if target == "running":
            if (
                job.status != "queued"
                or row.status != "active"
                or row.lease_expires_at <= now
                or job.hard_expires_at <= now
            ):
                raise RuntimeLeaseConflict("job cannot safely start or rerun")
            job.status = "running"
            job.started_at = now
        elif target in {"succeeded", "failed", "unknown"}:
            if job.status != "running":
                raise RuntimeLeaseConflict("only running jobs can record an outcome")
            if target == "succeeded":
                if result_digest is None:
                    raise InvalidInput("successful job needs a trusted result digest")
                _fingerprint(result_digest)
            job.status = target
            job.result_digest = result_digest if target == "succeeded" else None
            job.resolved_at = now
        elif target == "cancelled":
            if job.status != "queued":
                raise RuntimeLeaseConflict("running job cancellation is an external action")
            job.status = "cancelled"
            job.resolved_at = now
        else:
            raise InvalidInput("unsupported runtime job transition")
        job.version += 1
        self.app._audit(
            tx,
            actor=decision.actor_id,
            project=decision.project_id,
            action=f"runtime.job_{job.status}",
            target=job_uuid,
            event={"job_version": job.version, "runtime_session_uuid": str(runtime_uuid)},
        )
        return _job(job)

    async def mark_timed_out_jobs(self, tx: AsyncSession, *, limit: int = 64) -> int:
        if not 1 <= limit <= 256:
            raise InvalidInput("runtime job expiry batch outside allowed bounds")
        now = _now()
        rows = await tx.scalars(
            select(RuntimeJobRow)
            .where(
                RuntimeJobRow.status.in_(("queued", "running")),
                RuntimeJobRow.hard_expires_at <= now,
            )
            .order_by(RuntimeJobRow.hard_expires_at, RuntimeJobRow.job_uuid)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        count = 0
        for row in rows:
            # External effect may have committed after a worker timeout.
            row.status = "unknown" if row.status == "running" else "cancelled"
            row.resolved_at = now
            row.version += 1
            self.app._audit(
                tx,
                actor=None,
                project=PlatformProjectId(row.project_id),
                action="runtime.job_deadline",
                target=row.job_uuid,
                event={"job_status": row.status, "job_version": row.version},
            )
            count += 1
        return count

    async def inspect_open(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        *,
        kind: str,
        idempotency_key: str,
    ) -> RuntimeLease | None:
        """Read authoritative open intent without starting another OS process."""
        await self._authorize(tx, decision, kind, decision.project_id)
        digest = self._digest(idempotency_key)
        row = await tx.scalar(
            select(RuntimeSessionRow).where(
                RuntimeSessionRow.project_id == decision.project_id,
                RuntimeSessionRow.actor_user_id == decision.actor_id,
                RuntimeSessionRow.agent_session_uuid == decision.session_uuid,
                RuntimeSessionRow.owner_service_id == decision.service_id,
                RuntimeSessionRow.owner_instance == decision.instance_uuid,
                RuntimeSessionRow.kind == kind,
                RuntimeSessionRow.open_idempotency_digest == digest,
            )
        )
        return _lease(row) if row is not None else None

    async def inspect_job(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
        runtime_uuid: UUID,
        *,
        idempotency_key: str,
    ) -> RuntimeJob | None:
        """Never infer missing command ledger evidence means no side effect."""
        runtime = await tx.scalar(
            select(RuntimeSessionRow).where(
                RuntimeSessionRow.runtime_session_uuid == runtime_uuid,
                RuntimeSessionRow.project_id == decision.project_id,
            )
        )
        if runtime is None:
            raise AccessDenied("runtime not available for selected Project")
        await self._authorize(tx, decision, runtime.kind, decision.project_id)
        if (
            runtime.actor_user_id != decision.actor_id
            or runtime.agent_session_uuid != decision.session_uuid
            or runtime.owner_service_id != decision.service_id
            or runtime.owner_instance != decision.instance_uuid
        ):
            raise AccessDenied("runtime ownership mismatch")
        row = await tx.scalar(
            select(RuntimeJobRow).where(
                RuntimeJobRow.project_id == decision.project_id,
                RuntimeJobRow.runtime_session_uuid == runtime_uuid,
                RuntimeJobRow.actor_user_id == decision.actor_id,
                RuntimeJobRow.agent_session_uuid == decision.session_uuid,
                RuntimeJobRow.owner_service_id == decision.service_id,
                RuntimeJobRow.idempotency_digest == self._digest(idempotency_key),
            )
        )
        return _job(row) if row is not None else None
