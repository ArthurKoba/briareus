"""Read-only native Files root port over the existing Project directory layout.

A current mapping lease is mandatory, independent of the caller and Access
policy. This code only binds the configured <base>/<ProjectUUID> namespace
to safe descriptors. It never provisions roots, invents revisions or adapts
Rauthy/V2 facts into a legacy ProjectPermit.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, ExitStack, asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from modules.project_runtime.workspace_roots import (
    _DIR_FLAGS,
    ProjectRootRegistry,
    _open_beneath,
    _safe_directory,
)

from ._fd_snapshot import FilesNodeStamp, observe_root
from ._lease_deadline import ReadLeaseDeadline
from ._native_read import NativeFilesReadRequest
from ._read_adapter import FilesMcpReadUnavailable


class CurrentProjectMapping(Protocol):
    request_fingerprint: str
    actor_uuid: UUID
    project_uuid: UUID
    resource_revision: int
    expires_at: datetime

    async def validate_current(self) -> None: ...


class TrustedProjectMappingPort(Protocol):
    def hold_mapping(
        self, *, request: NativeFilesReadRequest, actor_uuid: UUID
    ) -> AbstractAsyncContextManager[CurrentProjectMapping]:
        """Return current owner revision for this Project's fixed namespace.

        The owner must reject missing/inactive mapping and unauthorized
        caller; exit must still uphold that mapping. This is not a raw
        HTTP DTO, a client-selected directory or an inode-derived revision.
        """
        ...


@dataclass(frozen=True, slots=True)
class _MappingBinding:
    fingerprint: str
    actor_uuid: UUID
    project_uuid: UUID
    revision: int
    expires_at: datetime


def _mapping_binding(
    mapping: CurrentProjectMapping, request: NativeFilesReadRequest, actor: UUID
) -> _MappingBinding:
    if (
        mapping.request_fingerprint != request.request_fingerprint
        or mapping.actor_uuid != actor
        or mapping.project_uuid != request.project_uuid
        or type(mapping.resource_revision) is not int
        or not 1 <= mapping.resource_revision <= 2**63 - 1
        or not isinstance(mapping.expires_at, datetime)
        or mapping.expires_at.tzinfo is None
        or mapping.expires_at <= datetime.now(UTC)
    ):
        raise FilesMcpReadUnavailable("FILES_CURRENT_MAPPING_INVALID")
    return _MappingBinding(
        request.request_fingerprint,
        actor,
        request.project_uuid,
        mapping.resource_revision,
        mapping.expires_at,
    )


@dataclass(slots=True)
class _HeldProjectRoot:
    registry: ProjectRootRegistry
    project_name: str
    base_fd: int
    root_fd: int
    observation: FilesNodeStamp
    stack: ExitStack = field(repr=False)

    def validate(self) -> None:
        if self.root_fd < 0 or self.base_fd < 0:
            raise FilesMcpReadUnavailable("FILES_PROJECT_ROOT_CLOSED")
        # Reopen the entire configured base, not only its former FD: a
        # renamed/replaced storage namespace must not keep an obsolete root.
        with self.registry._base_fd() as base:
            if not os.path.samestat(os.fstat(base), os.fstat(self.base_fd)):
                raise FilesMcpReadUnavailable("FILES_STORAGE_NAMESPACE_CHANGED")
            current = _open_beneath(base, self.project_name, _DIR_FLAGS)
            try:
                _safe_directory(current, expected_device=os.fstat(base).st_dev)
                if observe_root(current) != self.observation:
                    raise FilesMcpReadUnavailable("FILES_PROJECT_MAPPING_CHANGED")
                if observe_root(self.root_fd) != self.observation:
                    raise FilesMcpReadUnavailable("FILES_HELD_ROOT_CHANGED")
            finally:
                os.close(current)

    def close(self) -> None:
        self.root_fd = self.base_fd = -1
        self.stack.close()


def _open_project(registry: ProjectRootRegistry, project: UUID) -> _HeldProjectRoot:
    stack = ExitStack()
    try:
        base = stack.enter_context(registry._base_fd())
        root = _open_beneath(base, str(project), _DIR_FLAGS)
        stack.callback(os.close, root)
        _safe_directory(root, expected_device=os.fstat(base).st_dev)
        handle = _HeldProjectRoot(registry, str(project), base, root, observe_root(root), stack)
        handle.validate()
        return handle
    except BaseException:
        stack.close()
        raise


async def _finish_worker[T](task: asyncio.Task[T]) -> T:
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(BaseException):
            result = task.result()
            if isinstance(result, _HeldProjectRoot):
                result.close()
        raise


class _RegistryRootLease:
    def __init__(
        self,
        request: NativeFilesReadRequest,
        mapping: CurrentProjectMapping,
        binding: _MappingBinding,
        handle: _HeldProjectRoot,
    ) -> None:
        self.request_fingerprint = request.request_fingerprint
        self.project_uuid = request.project_uuid
        self.owner_revision = binding.revision
        self.root_fd = handle.root_fd
        self.root_observation = handle.observation
        self.expires_at = binding.expires_at
        self._request, self._mapping, self._binding, self._handle = (
            request,
            mapping,
            binding,
            handle,
        )
        self._closed = False
        self._deadline = ReadLeaseDeadline.capture(binding.expires_at)

    async def validate_current(self) -> None:
        if self._closed:
            raise FilesMcpReadUnavailable("FILES_PROJECT_ROOT_CLOSED")
        self._deadline.check()
        if await self._mapping.validate_current() is not None:
            raise FilesMcpReadUnavailable("FILES_CURRENT_MAPPING_INVALID")
        if (
            _mapping_binding(self._mapping, self._request, self._binding.actor_uuid)
            != self._binding
        ):
            raise FilesMcpReadUnavailable("FILES_CURRENT_MAPPING_CHANGED")
        await _finish_worker(asyncio.create_task(asyncio.to_thread(self._handle.validate)))
        self._deadline.check()
        if (
            _mapping_binding(self._mapping, self._request, self._binding.actor_uuid)
            != self._binding
        ):
            raise FilesMcpReadUnavailable("FILES_CURRENT_MAPPING_CHANGED")


class RegistryFilesRootPort:
    def __init__(
        self, *, base_root: Path, mappings: TrustedProjectMappingPort | None = None
    ) -> None:
        self._registry = ProjectRootRegistry(Path(base_root))
        self._mappings = mappings

    @asynccontextmanager
    async def hold_root(
        self, *, request: NativeFilesReadRequest, actor_uuid: UUID
    ) -> AsyncIterator[_RegistryRootLease]:
        if (
            self._mappings is None
            or not isinstance(request, NativeFilesReadRequest)
            or not isinstance(actor_uuid, UUID)
            or actor_uuid.version != 4
        ):
            raise FilesMcpReadUnavailable("FILES_CURRENT_MAPPING_REQUIRED")
        completed = False
        root_closed = False
        binding: _MappingBinding | None = None
        async with self._mappings.hold_mapping(request=request, actor_uuid=actor_uuid) as mapping:
            binding = _mapping_binding(mapping, request, actor_uuid)
            mapping_lease = ReadLeaseDeadline.capture(binding.expires_at)
            if await mapping.validate_current() is not None:
                raise FilesMcpReadUnavailable("FILES_CURRENT_MAPPING_INVALID")
            mapping_lease.check()
            if _mapping_binding(mapping, request, actor_uuid) != binding:
                raise FilesMcpReadUnavailable("FILES_CURRENT_MAPPING_CHANGED")
            handle = await _finish_worker(
                asyncio.create_task(
                    asyncio.to_thread(
                        _open_project,
                        self._registry,
                        request.project_uuid,
                    )
                )
            )
            scope: _RegistryRootLease | None = None
            try:
                # The opener may have waited past its original lease. Its
                # acquired FDs must be reclaimed even if lease construction
                # itself now rejects expiry or changed owner state.
                mapping_lease.check()
                scope = _RegistryRootLease(request, mapping, binding, handle)
                await scope.validate_current()
                yield scope
                await scope.validate_current()
                completed = True
            finally:
                if scope is not None:
                    scope._closed = True
                handle.close()
                if scope is not None:
                    scope.root_fd = -1
                root_closed = True
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        if (
            not completed
            or not root_closed
            or binding is None
            or binding.expires_at <= datetime.now(UTC)
        ):
            raise FilesMcpReadUnavailable("FILES_CURRENT_MAPPING_EXIT_INVALID")
        mapping_lease.check()
