"""Briareus Project Terminal trust gate; no shared shell or R6 lease owner.

Neither cwd, an AgentSession UUIDv4, a Python ProjectPermit nor a database
`active` row authorizes host execution. A9 must first accept a distinct,
signed owner_service_id/lease_nonce contract; C2 then needs an attested OS
worker with per-Project UID/mount namespace/cgroup v2 and hard process-tree
TTL. Until BOTH exist, Terminal fails closed before creating any OS process.
"""

from __future__ import annotations

from uuid import UUID

from modules.project_runtime import ProjectInvocation, ProjectRuntimeAuthority
from modules.project_runtime.workspace_roots import ProjectRootRegistry

from .project_isolation import ProjectIsolationAttestation, ProjectIsolationInspector


class ProjectTerminalExecutionUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProjectTerminalRuntime:
    """Only the signed A6 Project authority, not an in-memory process owner."""

    def __init__(
        self,
        *,
        authority: ProjectRuntimeAuthority,
        roots: ProjectRootRegistry,
        isolation: ProjectIsolationInspector | None = None,
    ) -> None:
        self.authority = authority
        self.roots = roots
        self.isolation = isolation

    @staticmethod
    def _uuid(value: UUID) -> None:
        if not isinstance(value, UUID) or value.version != 4:
            raise ProjectTerminalExecutionUnavailable("PROJECT_RUNTIME_SESSION_UUID_INVALID")

    async def open(
        self,
        invocation: ProjectInvocation,
        *,
        idle_seconds: float,
        hard_seconds: float,
    ) -> None:
        if (
            not isinstance(idle_seconds, (int, float))
            or not isinstance(hard_seconds, (int, float))
            or not 0 < idle_seconds <= hard_seconds <= 86400
        ):
            raise ProjectTerminalExecutionUnavailable("PROJECT_RUNTIME_TTL_INVALID")
        await self.authority.require(invocation, "terminal.attach")
        # A6 RuntimeOpenReceipt can commit a lease WITHOUT returning the
        # original owner nonce. Creating another local lease would strand the
        # DB session and let unsafe retries bypass CAS/cleanup ownership.
        raise ProjectTerminalExecutionUnavailable("PROJECT_A9_OWNER_NONCE_NOT_ACCEPTED")

    async def attach(self, invocation: ProjectInvocation, runtime_session_uuid: UUID) -> None:
        self._uuid(runtime_session_uuid)
        await self.authority.require(invocation, "terminal.attach")
        raise ProjectTerminalExecutionUnavailable("PROJECT_A9_SIGNED_LEASE_REQUIRED")

    async def close(
        self,
        invocation: ProjectInvocation,
        runtime_session_uuid: UUID,
        *,
        expected_revision: int,
    ) -> None:
        self._uuid(runtime_session_uuid)
        if type(expected_revision) is not int or expected_revision < 1:
            raise ProjectTerminalExecutionUnavailable("PROJECT_RUNTIME_CAS_INVALID")
        await self.authority.require(invocation, "terminal.attach")
        # Closing a DB row alone does not prove the cgroup/descendants were
        # reaped. Do not pretend a stale PID or local lease was its owner.
        raise ProjectTerminalExecutionUnavailable("PROJECT_OS_CLEANUP_ATTESTATION_REQUIRED")

    async def inspect_os_isolation(
        self, invocation: ProjectInvocation, *, runtime_session_uuid: UUID
    ) -> ProjectIsolationAttestation:
        self._uuid(runtime_session_uuid)
        await self.authority.require(invocation, "terminal.attach")
        # A separate OS attestation is useful only after Backend proves the
        # lease nonce+owner_service_id for THIS runtime/session/actor. Current
        # A6 source lacks that receipt, even if an OS inspector was injected.
        raise ProjectTerminalExecutionUnavailable("PROJECT_A9_SIGNED_LEASE_REQUIRED")

    async def execute(self, invocation: ProjectInvocation, command: str) -> None:
        if not isinstance(command, str) or not command.strip() or len(command) > 65536:
            raise ProjectTerminalExecutionUnavailable("PROJECT_TERMINAL_COMMAND_INVALID")
        await self.authority.require(invocation, "terminal.attach")
        raise ProjectTerminalExecutionUnavailable("PROJECT_TERMINAL_OS_OWNER_UNAVAILABLE")
