"""Unmounted Project/Terminal binding, independent of legacy workspace IDs.

This adapter manages authorization and metadata leases ONLY. It deliberately
cannot start a shell or privileged process: matching an OS working directory
to a Project UUID does not isolate filesystem, network, credentials or root.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from modules.project_runtime import (
    ProjectInvocation,
    ProjectRootRegistry,
    ProjectRuntimeAuthority,
    RuntimeLease,
    RuntimeLeaseRegistry,
)
from modules.project_runtime.runtime_owner import ProjectRuntimeOwner

from .project_isolation import (
    ProjectIsolationAttestation,
    ProjectIsolationInspector,
)


@dataclass(frozen=True, slots=True)
class ProjectTerminalAttachment:
    project_id: UUID
    runtime_lease: RuntimeLease


class ProjectTerminalRuntime:
    def __init__(
        self,
        *,
        authority: ProjectRuntimeAuthority,
        roots: ProjectRootRegistry,
        leases: RuntimeLeaseRegistry,
        owner: ProjectRuntimeOwner | None = None,
        isolation: ProjectIsolationInspector | None = None,
    ) -> None:
        self.authority = authority
        self.roots = roots
        self.leases = leases
        self.owner = owner
        self.isolation = isolation

    async def open(
        self,
        invocation: ProjectInvocation,
        *,
        idle_seconds: float,
        hard_seconds: float,
    ) -> ProjectTerminalAttachment:
        permit = await self.authority.require(invocation, "terminal.attach")
        if self.owner is None:
            raise ProjectTerminalExecutionUnavailable("PROJECT_DURABLE_LEASE_UNAVAILABLE")
        self.owner.require_available()

        def check_project_root() -> None:
            with self.roots.open(permit):
                pass

        await asyncio.to_thread(check_project_root)

        async def release_attachment() -> None:
            # No external process was started and no job may be auto-replayed.
            return None

        lease = await self.owner.open(
            permit,
            kind="terminal",
            idle_seconds=idle_seconds,
            hard_seconds=hard_seconds,
            cleanup=release_attachment,
        )
        return ProjectTerminalAttachment(permit.project_id, lease)

    async def attach(
        self, invocation: ProjectInvocation, runtime_session_uuid: UUID
    ) -> RuntimeLease:
        permit = await self.authority.require(invocation, "terminal.attach")
        if self.owner is None:
            raise ProjectTerminalExecutionUnavailable("PROJECT_DURABLE_LEASE_UNAVAILABLE")
        return await self.owner.attach(permit, runtime_session_uuid)

    async def close(
        self,
        invocation: ProjectInvocation,
        runtime_session_uuid: UUID,
        *,
        expected_revision: int,
    ) -> RuntimeLease:
        permit = await self.authority.require(invocation, "terminal.attach")
        if self.owner is None:
            raise ProjectTerminalExecutionUnavailable("PROJECT_DURABLE_LEASE_UNAVAILABLE")
        return await self.owner.close(
            permit, runtime_session_uuid, expected_revision=expected_revision
        )

    async def inspect_os_isolation(
        self, invocation: ProjectInvocation, *, runtime_session_uuid: UUID
    ) -> ProjectIsolationAttestation:
        """Read approved OS attestations only, never start a host shell."""
        permit = await self.authority.require(invocation, "terminal.attach")
        if self.owner is None or self.isolation is None:
            raise ProjectTerminalExecutionUnavailable("PROJECT_OS_SUPERVISOR_UNAVAILABLE")
        lease = await self.owner.status(permit, runtime_session_uuid)
        if lease.kind != "terminal" or lease.state != "active":
            raise ProjectTerminalExecutionUnavailable("PROJECT_TERMINAL_SESSION_UNAVAILABLE")
        return await self.isolation.attest(invocation, runtime_session_uuid=runtime_session_uuid)

    async def execute(self, invocation: ProjectInvocation, command: str) -> None:
        # Check access before reporting the missing operating-system confinement.
        await self.authority.require(invocation, "terminal.attach")
        if not command.strip():
            raise ProjectTerminalExecutionUnavailable("PROJECT_TERMINAL_COMMAND_REQUIRED")
        raise ProjectTerminalExecutionUnavailable("PROJECT_TERMINAL_ISOLATION_UNAVAILABLE")


class ProjectTerminalExecutionUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
