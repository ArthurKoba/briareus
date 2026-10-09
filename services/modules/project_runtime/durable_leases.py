"""Fail-closed persistent RuntimeSession journal adapter, awaiting Backend C1-B2.

No SQL table or URL is invented here. A Backend-owned compare-and-swap port
must persist the owner UUID, Project, state, revision and UTC deadlines. In
particular, restart NEVER replays a Terminal command or creates a browser.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from .authorization import ProjectPermit
from .sessions import RuntimeKind, RuntimeLease, RuntimeSessionError

RuntimeRecordState = Literal["active", "closing", "closed", "lost"]


@dataclass(frozen=True, slots=True)
class DurableRuntimeRecord:
    runtime_session_uuid: UUID
    project_id: UUID
    agent_session_uuid: UUID
    owner_actor_id: UUID
    owner_instance_uuid: UUID
    kind: RuntimeKind
    revision: int
    state: RuntimeRecordState
    idle_expires_at: datetime
    hard_expires_at: datetime


class DurableLeasePort(Protocol):
    async def create(self, record: DurableRuntimeRecord) -> None: ...

    async def compare_and_set(
        self,
        *,
        project_id: UUID,
        runtime_session_uuid: UUID,
        expected_revision: int,
        next_record: DurableRuntimeRecord,
    ) -> bool: ...

    async def records_for_instance(
        self, owner_instance_uuid: UUID
    ) -> tuple[DurableRuntimeRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class VerifiedRuntimeRecovery:
    """Backend-attested service owner-fencing decision, never user metadata."""

    previous_instance_uuid: UUID
    new_instance_uuid: UUID
    decision_revision: int
    expires_at: datetime


class RuntimeRecoveryVerifier(Protocol):
    async def authorize_instance_recovery(
        self,
        *,
        previous_instance_uuid: UUID,
        new_instance_uuid: UUID,
        service_evidence: object,
    ) -> VerifiedRuntimeRecovery: ...


class ProjectRuntimeJournal:
    """CAS-fenced durable projection, deliberately unconfigured by default."""

    def __init__(
        self,
        port: DurableLeasePort | None = None,
        *,
        instance_uuid: UUID | None = None,
        operation_timeout_seconds: float = 10.0,
        recovery_verifier: RuntimeRecoveryVerifier | None = None,
    ) -> None:
        if not math.isfinite(operation_timeout_seconds) or not 0 < operation_timeout_seconds <= 300:
            raise ValueError("durable lease operation timeout must be finite and positive")
        self._operation_timeout_seconds = operation_timeout_seconds
        self._port = port
        self._recovery_verifier = recovery_verifier
        self._current: dict[UUID, DurableRuntimeRecord] = {}
        self._lock = asyncio.Lock()
        self.instance_uuid = instance_uuid or uuid4()
        if self.instance_uuid.version != 4:
            raise ValueError("instance UUID must be version 4")

    @staticmethod
    def _required(port: DurableLeasePort | None) -> DurableLeasePort:
        if port is None:
            raise RuntimeSessionError("RUNTIME_DURABLE_PORT_UNAVAILABLE")
        return port

    def require_available(self) -> None:
        self._required(self._port)

    async def current(
        self, permit: ProjectPermit, runtime_session_uuid: UUID
    ) -> DurableRuntimeRecord:
        self.require_available()
        async with self._lock:
            record = self._current.get(runtime_session_uuid)
            if (
                record is None
                or record.project_id != permit.project_id
                or record.owner_actor_id != permit.actor_id
                or record.agent_session_uuid != permit.session_uuid
            ):
                raise RuntimeSessionError("RUNTIME_DURABLE_SESSION_NOT_FOUND")
            return record

    async def current_project_owned(
        self, project_id: UUID, runtime_session_uuid: UUID
    ) -> DurableRuntimeRecord:
        """Internal supervisor-only lookup, never callable through agent MCP."""
        self.require_available()
        async with self._lock:
            record = self._current.get(runtime_session_uuid)
            if (
                record is None
                or record.project_id != project_id
                or record.owner_instance_uuid != self.instance_uuid
            ):
                raise RuntimeSessionError("RUNTIME_DURABLE_SESSION_NOT_FOUND")
            return record

    async def forget_closed(self, runtime_session_uuid: UUID) -> None:
        """Drop memory-only metadata after local closure; preserve DB audit."""
        self.require_available()
        async with self._lock:
            record = self._current.get(runtime_session_uuid)
            if record is None or record.owner_instance_uuid != self.instance_uuid:
                raise RuntimeSessionError("RUNTIME_DURABLE_SESSION_NOT_FOUND")
            if record.state != "closed":
                raise RuntimeSessionError("RUNTIME_DURABLE_TOMBSTONE_NOT_CLOSED")
            del self._current[runtime_session_uuid]

    @staticmethod
    def from_local(lease: RuntimeLease, owner_instance_uuid: UUID) -> DurableRuntimeRecord:
        now = time.monotonic()
        wall = datetime.now(UTC)
        idle = wall + timedelta(seconds=max(0.0, lease.idle_deadline - now))
        hard = wall + timedelta(seconds=max(0.0, lease.hard_deadline - now))
        if not all(math.isfinite(value) for value in (lease.idle_deadline, lease.hard_deadline)):
            raise RuntimeSessionError("RUNTIME_TTL_INVALID")
        return DurableRuntimeRecord(
            runtime_session_uuid=lease.runtime_session_uuid,
            project_id=lease.project_id,
            agent_session_uuid=lease.agent_session_uuid,
            owner_actor_id=lease.opened_by,
            owner_instance_uuid=owner_instance_uuid,
            kind=lease.kind,
            revision=lease.revision,
            state=lease.state,
            idle_expires_at=idle,
            hard_expires_at=hard,
        )

    async def open(self, permit: ProjectPermit, lease: RuntimeLease) -> DurableRuntimeRecord:
        port = self._required(self._port)
        if (
            lease.project_id != permit.project_id
            or lease.opened_by != permit.actor_id
            or lease.agent_session_uuid != permit.session_uuid
            or lease.state != "active"
            or lease.revision != 1
        ):
            raise RuntimeSessionError("RUNTIME_DURABLE_OWNER_INVALID")
        record = self.from_local(lease, self.instance_uuid)
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                await port.create(record)
        except Exception as exc:
            # A timed-out create may have committed remotely; no retry.
            raise RuntimeSessionError("RUNTIME_DURABLE_CREATE_OUTCOME_UNKNOWN") from exc
        async with self._lock:
            self._current[record.runtime_session_uuid] = record
        return record

    async def transition(
        self, before: DurableRuntimeRecord, after: RuntimeLease
    ) -> DurableRuntimeRecord:
        """CAS one transition without extending the original hard lease.

        Concurrent transitions from one service instance are serialized. If
        Backend CAS has an uncertain outcome, retain the prior local record
        and refuse a later transition until service-side reconciliation.
        """
        port = self._required(self._port)
        if (
            before.owner_instance_uuid != self.instance_uuid
            or before.runtime_session_uuid != after.runtime_session_uuid
            or before.project_id != after.project_id
            or before.owner_actor_id != after.opened_by
            or before.agent_session_uuid != after.agent_session_uuid
            or before.kind != after.kind
            or after.revision != before.revision + 1
        ):
            raise RuntimeSessionError("RUNTIME_DURABLE_TRANSITION_INVALID")
        allowed_states: dict[RuntimeRecordState, frozenset[RuntimeRecordState]] = {
            "active": frozenset({"active", "closed", "lost"}),
            "lost": frozenset({"closed", "lost"}),
            "closing": frozenset({"closed", "lost"}),
            "closed": frozenset(),
        }
        if after.state not in allowed_states[before.state]:
            raise RuntimeSessionError("RUNTIME_DURABLE_STATE_INVALID")
        candidate = self.from_local(after, self.instance_uuid)
        # An original hard deadline is IMMUTABLE. Allowing +2 seconds on
        # every attach would let repeated keep-alive calls extend the hard
        # lease indefinitely.
        if candidate.hard_expires_at > before.hard_expires_at + timedelta(milliseconds=100):
            raise RuntimeSessionError("RUNTIME_HARD_LEASE_EXTENSION_DENIED")
        if after.state == "active" and datetime.now(UTC) >= min(
            before.idle_expires_at, before.hard_expires_at
        ):
            raise RuntimeSessionError("RUNTIME_DURABLE_SESSION_EXPIRED")
        next_record = replace(
            candidate,
            hard_expires_at=before.hard_expires_at,
            idle_expires_at=min(candidate.idle_expires_at, before.hard_expires_at),
        )
        async with self._lock:
            stored = self._current.get(after.runtime_session_uuid)
            if stored is None or stored != before:
                raise RuntimeSessionError("RUNTIME_DURABLE_LOCAL_FENCE_STALE")
            try:
                async with asyncio.timeout(self._operation_timeout_seconds):
                    changed = await port.compare_and_set(
                        project_id=after.project_id,
                        runtime_session_uuid=after.runtime_session_uuid,
                        expected_revision=before.revision,
                        next_record=next_record,
                    )
            except Exception as exc:
                # A timeout can mean the CAS succeeded remotely. No retry.
                raise RuntimeSessionError("RUNTIME_DURABLE_OUTCOME_UNKNOWN") from exc
            if not changed:
                raise RuntimeSessionError("RUNTIME_DURABLE_FENCE_STALE")
            self._current[after.runtime_session_uuid] = next_record
        return next_record

    async def reconcile_previous_instance(
        self,
        previous_instance_uuid: UUID,
        *,
        service_evidence: object | None = None,
    ) -> tuple[DurableRuntimeRecord, ...]:
        """Fence orphaned prior-owner records as lost, never revive processes.

        The caller must have authenticated ownership of the previous runtime
        service instance; a UUID submitted by an MCP client is not enough.
        Requires Backend CAS and a separately reviewed OS worker cleanup.
        """
        port = self._required(self._port)
        if (
            not isinstance(previous_instance_uuid, UUID)
            or previous_instance_uuid == self.instance_uuid
        ):
            raise RuntimeSessionError("RUNTIME_OWNER_INVALID")
        if self._recovery_verifier is None or service_evidence is None:
            raise RuntimeSessionError("RUNTIME_RECOVERY_AUTHORITY_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                decision = await self._recovery_verifier.authorize_instance_recovery(
                    previous_instance_uuid=previous_instance_uuid,
                    new_instance_uuid=self.instance_uuid,
                    service_evidence=service_evidence,
                )
        except Exception as exc:
            raise RuntimeSessionError("RUNTIME_RECOVERY_IDENTITY_UNAVAILABLE") from exc
        if (
            not isinstance(decision, VerifiedRuntimeRecovery)
            or decision.previous_instance_uuid != previous_instance_uuid
            or decision.new_instance_uuid != self.instance_uuid
            or type(decision.decision_revision) is not int
            or decision.decision_revision < 1
            or not isinstance(decision.expires_at, datetime)
            or decision.expires_at.tzinfo is None
            or decision.expires_at <= datetime.now(UTC)
        ):
            raise RuntimeSessionError("RUNTIME_RECOVERY_IDENTITY_INVALID")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                old_records = await port.records_for_instance(previous_instance_uuid)
        except Exception as exc:
            raise RuntimeSessionError("RUNTIME_DURABLE_READ_UNAVAILABLE") from exc
        if len(old_records) > 10000:
            raise RuntimeSessionError("RUNTIME_RECONCILE_LIMIT_EXCEEDED")
        marked: list[DurableRuntimeRecord] = []
        for old in old_records:
            if datetime.now(UTC) >= decision.expires_at:
                raise RuntimeSessionError("RUNTIME_RECOVERY_DECISION_EXPIRED")
            if old.owner_instance_uuid != previous_instance_uuid:
                raise RuntimeSessionError("RUNTIME_OWNER_MISMATCH")
            if old.state in {"closed", "lost"}:
                continue
            next_record = replace(old, state="lost", revision=old.revision + 1)
            try:
                async with asyncio.timeout(self._operation_timeout_seconds):
                    updated = await port.compare_and_set(
                        project_id=old.project_id,
                        runtime_session_uuid=old.runtime_session_uuid,
                        expected_revision=old.revision,
                        next_record=next_record,
                    )
            except Exception as exc:
                raise RuntimeSessionError("RUNTIME_DURABLE_WRITE_UNAVAILABLE") from exc
            if not updated:
                raise RuntimeSessionError("RUNTIME_DURABLE_FENCE_STALE")
            marked.append(next_record)
        return tuple(marked)
