"""One-process Project Runtime owner with Backend CAS fencing.

No port -> no runtime lease. Source-only private adapter; it cannot create
an OS sandbox, kill a detached command, or authenticate a client by UUID.
"""

from __future__ import annotations

import asyncio
import math
from contextlib import suppress
from uuid import UUID

from .authorization import ProjectPermit
from .durable_leases import DurableRuntimeRecord, ProjectRuntimeJournal
from .sessions import Cleanup, RuntimeKind, RuntimeLease, RuntimeLeaseRegistry, RuntimeSessionError


class ProjectRuntimeOwner:
    def __init__(self, local: RuntimeLeaseRegistry, journal: ProjectRuntimeJournal) -> None:
        self._local = local
        self._journal = journal
        # Local transition + remote CAS must be serialized as one ownership
        # decision; otherwise two concurrent attaches can race a stale local
        # revision with a successful remote CAS.
        self._operations = asyncio.Lock()

    def require_available(self) -> None:
        self._journal.require_available()

    async def open(
        self,
        permit: ProjectPermit,
        *,
        kind: RuntimeKind,
        idle_seconds: float,
        hard_seconds: float,
        cleanup: Cleanup,
    ) -> RuntimeLease:
        self.require_available()
        async with self._operations:
            lease = await self._local.open(
                permit,
                kind=kind,
                idle_seconds=idle_seconds,
                hard_seconds=hard_seconds,
                cleanup=cleanup,
            )
            try:
                await self._journal.open(permit, lease)
            except BaseException:
                # An uncertain durable claim may be present remotely. Never
                # expose its local counterpart or start another worker.
                with suppress(BaseException):
                    await self._local.close(
                        permit, lease.runtime_session_uuid, expected_revision=lease.revision
                    )
                raise
            return lease

    async def _before(
        self, permit: ProjectPermit, runtime_session_uuid: UUID
    ) -> DurableRuntimeRecord:
        record = await self._journal.current(permit, runtime_session_uuid)
        if (
            record.project_id != permit.project_id
            or record.agent_session_uuid != permit.session_uuid
            or record.owner_actor_id != permit.actor_id
            or record.runtime_session_uuid != runtime_session_uuid
            or record.owner_instance_uuid != self._journal.instance_uuid
        ):
            raise RuntimeSessionError("RUNTIME_DURABLE_OWNERSHIP_MISMATCH")
        return record

    async def status(self, permit: ProjectPermit, runtime_session_uuid: UUID) -> RuntimeLease:
        """Read only a live, owned lease; no implicit touch/revision change."""
        async with self._operations:
            current = await self._before(permit, runtime_session_uuid)
            lease = await self._local.status(permit, runtime_session_uuid)
            if (
                lease.revision != current.revision
                or lease.state != current.state
                or lease.agent_session_uuid != current.agent_session_uuid
                or lease.project_id != current.project_id
                or lease.opened_by != current.owner_actor_id
            ):
                raise RuntimeSessionError("RUNTIME_DURABLE_FENCE_STALE")
            return lease

    async def attach(self, permit: ProjectPermit, runtime_session_uuid: UUID) -> RuntimeLease:
        async with self._operations:
            before = await self._before(permit, runtime_session_uuid)
            lease = await self._local.attach(permit, runtime_session_uuid)
            await self._journal.transition(before, lease)
            return lease

    async def close(
        self, permit: ProjectPermit, runtime_session_uuid: UUID, *, expected_revision: int
    ) -> RuntimeLease:
        async with self._operations:
            before = await self._before(permit, runtime_session_uuid)
            if before.revision != expected_revision:
                raise RuntimeSessionError("RUNTIME_DURABLE_FENCE_STALE")
            lease = await self._local.close(
                permit, runtime_session_uuid, expected_revision=expected_revision
            )
            await self._journal.transition(before, lease)
            return lease

    async def mark_lost(
        self, permit: ProjectPermit, runtime_session_uuid: UUID, *, expected_revision: int
    ) -> RuntimeLease:
        async with self._operations:
            before = await self._before(permit, runtime_session_uuid)
            if before.revision != expected_revision:
                raise RuntimeSessionError("RUNTIME_DURABLE_FENCE_STALE")
            lease = await self._local.mark_lost(
                permit, runtime_session_uuid, expected_revision=expected_revision
            )
            await self._journal.transition(before, lease)
            return lease

    async def cleanup_lost(
        self, permit: ProjectPermit, runtime_session_uuid: UUID, *, expected_revision: int
    ) -> RuntimeLease:
        async with self._operations:
            before = await self._before(permit, runtime_session_uuid)
            if before.revision != expected_revision:
                raise RuntimeSessionError("RUNTIME_DURABLE_FENCE_STALE")
            lease = await self._local.cleanup_lost(
                permit, runtime_session_uuid, expected_revision=expected_revision
            )
            await self._journal.transition(before, lease)
            return lease

    async def expire(self) -> tuple[RuntimeLease, ...]:
        self.require_available()
        async with self._operations:
            results = await self._local.expire()
            for lease in results:
                record = await self._journal.current_project_owned(
                    lease.project_id, lease.runtime_session_uuid
                )
                await self._journal.transition(record, lease)
            return tuple(results)

    async def shutdown(self) -> tuple[RuntimeLease, ...]:
        self.require_available()
        async with self._operations:
            results = await self._local.shutdown()
            for lease in results:
                before = await self._journal.current_project_owned(
                    lease.project_id, lease.runtime_session_uuid
                )
                await self._journal.transition(before, lease)
            return tuple(results)

    async def run_reaper(self, stop: asyncio.Event, *, interval_seconds: float = 1.0) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("reaper interval must be finite and positive")
        self.require_available()
        while not stop.is_set():
            await self.expire()
            async with self._operations:
                # A lifetime of short Web sessions must not exhaust the
                # local capacity. Retain all LOST/uncertain records for
                # reconciliation; prune only closed durable-confirmed IDs.
                for key in await self._local.closed_candidates():
                    await self._journal.forget_closed(key)
                    await self._local.remove_closed(key)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
