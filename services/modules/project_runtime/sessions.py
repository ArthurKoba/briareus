"""Local non-durable ownership and lease fencing for private runtime adapters.

This does not replace durable Project/AgentSession grants or a privileged
process supervisor. Leases are never reconstructed by restarting a command.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from .authorization import ProjectPermit

RuntimeKind = Literal["terminal", "internal_browser", "remote_browser", "reverse"]
Cleanup = Callable[[], Awaitable[None]]


class RuntimeSessionError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RuntimeLease:
    runtime_session_uuid: UUID
    project_id: UUID
    agent_session_uuid: UUID
    opened_by: UUID
    attached_by: UUID
    kind: RuntimeKind
    revision: int
    idle_deadline: float
    hard_deadline: float
    state: Literal["active", "closing", "closed", "lost"]


@dataclass(slots=True)
class _Entry:
    lease: RuntimeLease
    idle_seconds: float
    cleanup: Cleanup
    closed_at: float | None = None
    cleanup_task: asyncio.Task[RuntimeLease] | None = None


class RuntimeLeaseRegistry:
    """One-process registry with monotonic TTL and revision-fenced attaches.

    The orchestrating service must run `run_reaper()` with its own lifetime.
    Without a separate kill-capable supervisor this must not authorize shell
    execution, because a Python task cannot survive a service crash.
    """

    def __init__(
        self,
        *,
        cleanup_timeout_seconds: float = 10.0,
        max_records: int = 1024,
        max_parallel_cleanups: int = 8,
        closed_retention_seconds: float = 3600.0,
    ) -> None:
        if not math.isfinite(cleanup_timeout_seconds) or cleanup_timeout_seconds <= 0:
            raise ValueError("cleanup_timeout_seconds must be finite and positive")
        if max_records < 1 or max_parallel_cleanups < 1:
            raise ValueError("runtime capacity and cleanup concurrency must be positive")
        if not math.isfinite(closed_retention_seconds) or closed_retention_seconds < 0:
            raise ValueError("closed_retention_seconds must be finite and nonnegative")
        self._cleanup_timeout_seconds = cleanup_timeout_seconds
        self._max_records = max_records
        self._cleanup_semaphore = asyncio.Semaphore(max_parallel_cleanups)
        self._closed_retention_seconds = closed_retention_seconds
        self._entries: dict[UUID, _Entry] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _verify(permit: ProjectPermit, lease: RuntimeLease) -> None:
        if (
            not isinstance(permit.expires_at, datetime)
            or permit.expires_at.tzinfo is None
            or permit.expires_at <= datetime.now(UTC)
            or type(permit.decision_version) is not int
            or permit.decision_version < 1
        ):
            raise RuntimeSessionError("RUNTIME_PERMISSION_EXPIRED")
        if permit.project_id != lease.project_id:
            raise RuntimeSessionError("RUNTIME_PROJECT_MISMATCH")
        # A RuntimeSession is NOT an AgentSession or a Chat ID. Its access is
        # bound to the verified creating AgentSession until an explicit,
        # Backend-approved delegation contract exists; Project membership
        # alone must not grant access to another user's live browser/shell.
        if permit.session_uuid != lease.agent_session_uuid:
            raise RuntimeSessionError("RUNTIME_AGENT_SESSION_MISMATCH")
        if permit.actor_id != lease.opened_by:
            raise RuntimeSessionError("RUNTIME_ACTOR_MISMATCH")
        if lease.kind == "terminal" and permit.action != "terminal.attach":
            raise RuntimeSessionError("RUNTIME_PERMISSION_DENIED")
        if lease.kind == "internal_browser" and permit.action != "web.internal":
            raise RuntimeSessionError("RUNTIME_PERMISSION_DENIED")
        if lease.kind == "remote_browser" and permit.action != "web.remote":
            raise RuntimeSessionError("RUNTIME_PERMISSION_DENIED")
        if lease.kind == "reverse" and permit.action != "reverse.import":
            raise RuntimeSessionError("RUNTIME_PERMISSION_DENIED")

    async def open(
        self,
        permit: ProjectPermit,
        *,
        kind: RuntimeKind,
        idle_seconds: float,
        hard_seconds: float,
        cleanup: Cleanup,
    ) -> RuntimeLease:
        if (
            not math.isfinite(idle_seconds)
            or not math.isfinite(hard_seconds)
            or not 0 < idle_seconds <= hard_seconds
        ):
            raise RuntimeSessionError("RUNTIME_TTL_INVALID")
        if kind not in {"terminal", "internal_browser", "remote_browser", "reverse"}:
            raise RuntimeSessionError("RUNTIME_KIND_INVALID")
        now = time.monotonic()
        lease = RuntimeLease(
            runtime_session_uuid=uuid4(),
            project_id=permit.project_id,
            agent_session_uuid=permit.session_uuid,
            opened_by=permit.actor_id,
            attached_by=permit.actor_id,
            kind=kind,
            revision=1,
            idle_deadline=now + idle_seconds,
            hard_deadline=now + hard_seconds,
            state="active",
        )
        self._verify(permit, lease)
        async with self._lock:
            if len(self._entries) >= self._max_records:
                raise RuntimeSessionError("RUNTIME_CAPACITY_REACHED")
            self._entries[lease.runtime_session_uuid] = _Entry(lease, idle_seconds, cleanup)
        return lease

    async def attach(self, permit: ProjectPermit, runtime_session_uuid: UUID) -> RuntimeLease:
        now = time.monotonic()
        async with self._lock:
            entry = self._entries.get(runtime_session_uuid)
            if entry is None:
                raise RuntimeSessionError("RUNTIME_SESSION_NOT_FOUND")
            lease = entry.lease
            self._verify(permit, lease)
            if lease.state != "active":
                raise RuntimeSessionError("RUNTIME_SESSION_CLOSED")
            if now >= min(lease.idle_deadline, lease.hard_deadline):
                raise RuntimeSessionError("RUNTIME_SESSION_EXPIRED")
            entry.lease = replace(
                lease,
                attached_by=permit.actor_id,
                revision=lease.revision + 1,
                idle_deadline=min(now + entry.idle_seconds, lease.hard_deadline),
            )
            return entry.lease

    async def close(
        self,
        permit: ProjectPermit,
        runtime_session_uuid: UUID,
        *,
        expected_revision: int,
    ) -> RuntimeLease:
        async with self._lock:
            entry = self._entries.get(runtime_session_uuid)
            if entry is None:
                raise RuntimeSessionError("RUNTIME_SESSION_NOT_FOUND")
            self._verify(permit, entry.lease)
            if entry.lease.state != "active":
                raise RuntimeSessionError("RUNTIME_SESSION_CLOSED")
            if entry.lease.revision != expected_revision:
                raise RuntimeSessionError("RUNTIME_LEASE_STALE")
            entry.lease = replace(entry.lease, state="closing", revision=expected_revision + 1)
        return await self._cleanup_entry_bounded(entry)

    async def _cleanup_entry_bounded(self, entry: _Entry) -> RuntimeLease:
        # The caller may disconnect or cancel after a durable state change.
        # The owned cleanup must still finish, and concurrent reaper/shutdown
        # callers must await the SAME callback rather than double-disconnect.
        async with self._lock:
            task = entry.cleanup_task
            if task is None:
                task = asyncio.create_task(self._run_cleanup(entry))
                entry.cleanup_task = task
        return await asyncio.shield(task)

    async def _run_cleanup(self, entry: _Entry) -> RuntimeLease:
        async with self._cleanup_semaphore:
            return await self._cleanup_entry(entry)

    async def _cleanup_entry(self, entry: _Entry) -> RuntimeLease:
        cancellation: asyncio.CancelledError | None = None
        try:
            await asyncio.wait_for(entry.cleanup(), timeout=self._cleanup_timeout_seconds)
        except asyncio.CancelledError as exc:
            cancellation = exc
            state: Literal["closed", "lost"] = "lost"
        except Exception:
            state = "lost"
        else:
            state = "closed"
        async with self._lock:
            entry.lease = replace(entry.lease, state=state)
            entry.closed_at = time.monotonic()
            result = entry.lease
        if cancellation is not None:
            raise cancellation
        return result

    async def expire(self) -> list[RuntimeLease]:
        now = time.monotonic()
        async with self._lock:
            entries: list[_Entry] = []
            for entry in self._entries.values():
                lease = entry.lease
                if lease.state == "active" and now >= min(lease.idle_deadline, lease.hard_deadline):
                    entry.lease = replace(lease, state="closing", revision=lease.revision + 1)
                    entries.append(entry)
                elif lease.state == "closing":
                    # An earlier caller may have been cancelled between
                    # changing state and creating its protected cleanup task.
                    entries.append(entry)
        return list(
            await asyncio.gather(*(self._cleanup_entry_bounded(entry) for entry in entries))
        )

    async def mark_lost(
        self,
        permit: ProjectPermit,
        runtime_session_uuid: UUID,
        *,
        expected_revision: int,
    ) -> RuntimeLease:
        """Fence an unreachable runtime; never replay its previous command.

        This does not attest that an OS process is stopped. The original
        supervisor must reconcile external process/cgroup state separately.
        """
        async with self._lock:
            entry = self._entries.get(runtime_session_uuid)
            if entry is None:
                raise RuntimeSessionError("RUNTIME_SESSION_NOT_FOUND")
            self._verify(permit, entry.lease)
            if entry.lease.state != "active":
                raise RuntimeSessionError("RUNTIME_SESSION_CLOSED")
            if entry.lease.revision != expected_revision:
                raise RuntimeSessionError("RUNTIME_LEASE_STALE")
            entry.lease = replace(entry.lease, state="lost", revision=expected_revision + 1)
            entry.closed_at = time.monotonic()
            return entry.lease

    async def cleanup_lost(
        self,
        permit: ProjectPermit,
        runtime_session_uuid: UUID,
        *,
        expected_revision: int,
    ) -> RuntimeLease:
        """Retry only an explicitly owned idempotent cleanup, never work replay."""
        async with self._lock:
            entry = self._entries.get(runtime_session_uuid)
            if entry is None:
                raise RuntimeSessionError("RUNTIME_SESSION_NOT_FOUND")
            self._verify(permit, entry.lease)
            if entry.lease.state != "lost":
                raise RuntimeSessionError("RUNTIME_SESSION_NOT_LOST")
            if entry.lease.revision != expected_revision:
                raise RuntimeSessionError("RUNTIME_LEASE_STALE")
            if entry.cleanup_task is not None and not entry.cleanup_task.done():
                raise RuntimeSessionError("RUNTIME_CLEANUP_IN_PROGRESS")
            entry.cleanup_task = None
            entry.lease = replace(entry.lease, state="closing", revision=expected_revision + 1)
        return await self._cleanup_entry_bounded(entry)

    async def shutdown(self) -> list[RuntimeLease]:
        """Disconnect all owned resources during orderly service shutdown.

        Remote browsers receive only the configured `disconnect` callback;
        unmanaged external Chrome/OS processes are never forcibly killed.
        """
        async with self._lock:
            entries: list[_Entry] = []
            for entry in self._entries.values():
                if entry.lease.state == "active":
                    entry.lease = replace(
                        entry.lease, state="closing", revision=entry.lease.revision + 1
                    )
                    entries.append(entry)
                elif entry.lease.state == "closing":
                    entries.append(entry)
        return list(
            await asyncio.gather(*(self._cleanup_entry_bounded(entry) for entry in entries))
        )

    async def status(self, permit: ProjectPermit, runtime_session_uuid: UUID) -> RuntimeLease:
        async with self._lock:
            entry = self._entries.get(runtime_session_uuid)
            if entry is None:
                raise RuntimeSessionError("RUNTIME_SESSION_NOT_FOUND")
            self._verify(permit, entry.lease)
            if entry.lease.state == "active" and time.monotonic() >= min(
                entry.lease.idle_deadline, entry.lease.hard_deadline
            ):
                raise RuntimeSessionError("RUNTIME_SESSION_EXPIRED")
            return entry.lease

    async def run_reaper(self, stop: asyncio.Event, *, interval_seconds: float = 1.0) -> None:
        """Sweep idle/hard TTLs until shutdown; never replay a lost process."""
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise RuntimeSessionError("RUNTIME_SWEEP_INTERVAL_INVALID")
        while not stop.is_set():
            await self.expire()
            await self.collect_closed(older_than_seconds=self._closed_retention_seconds)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue

    async def closed_candidates(self) -> tuple[UUID, ...]:
        """Snapshot aged closed IDs; durable journal must confirm before purge."""
        cutoff = time.monotonic() - self._closed_retention_seconds
        async with self._lock:
            return tuple(
                key
                for key, entry in self._entries.items()
                if entry.lease.state == "closed"
                and entry.closed_at is not None
                and entry.closed_at <= cutoff
            )

    async def remove_closed(self, runtime_session_uuid: UUID) -> bool:
        """Prune only an aged local tombstone after durable confirmation."""
        cutoff = time.monotonic() - self._closed_retention_seconds
        async with self._lock:
            entry = self._entries.get(runtime_session_uuid)
            if entry is None:
                return False
            if entry.lease.state != "closed" or entry.closed_at is None or entry.closed_at > cutoff:
                raise RuntimeSessionError("RUNTIME_TOMBSTONE_NOT_CLOSED")
            del self._entries[runtime_session_uuid]
            return True

    async def collect_closed(self, *, older_than_seconds: float) -> int:
        """Trim only completed metadata; lost cleanup remains for reconciliation."""
        if not math.isfinite(older_than_seconds) or older_than_seconds < 0:
            raise RuntimeSessionError("RUNTIME_RETENTION_INVALID")
        cutoff = time.monotonic() - older_than_seconds
        async with self._lock:
            selected = [
                runtime_session_uuid
                for runtime_session_uuid, entry in self._entries.items()
                if entry.lease.state == "closed"
                and entry.closed_at is not None
                and entry.closed_at <= cutoff
            ]
            for runtime_session_uuid in selected:
                del self._entries[runtime_session_uuid]
        return len(selected)
