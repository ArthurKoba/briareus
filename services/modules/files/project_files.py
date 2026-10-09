"""Private Files application adapter with a mandatory authorization port.

Never bind these methods to FastMCP or HTTP until the backend approves C1-B/C2.
Existing public Files tools keep using WorkspaceFileStore unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from uuid import UUID

from modules.project_runtime import (
    ProjectAccessDenied,
    ProjectInvocation,
    ProjectPermit,
    ProjectRootRegistry,
    ProjectRuntimeAuthority,
)
from modules.project_runtime.storage_quota import ProjectQuotaError, ProjectQuotaGuard
from modules.project_runtime.workspace_roots import ProjectFileError

from .a5_quota import A5FileQuotaFlow, A5FilesLedgerError
from .project_workspace import (
    ProjectFileEntry,
    ProjectFilePage,
    ProjectFileSnapshot,
    ProjectFileWriteStage,
    ProjectWorkspaceFiles,
    _components,
)


async def _drain_cancellable_file_io[**P, T](
    func: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Never close a staging fd while a non-cancellable OS thread uses it."""
    pending = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        # A second cancellation must not make stage.close race a worker fd.
        while not pending.done():
            try:
                await asyncio.shield(pending)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(BaseException):
            pending.result()
        raise


class ProjectFilesService:
    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        roots: ProjectRootRegistry,
        *,
        max_file_bytes: int,
        quota: ProjectQuotaGuard | None = None,
        a5_quota: A5FileQuotaFlow | None = None,
    ) -> None:
        self.quota = quota or ProjectQuotaGuard()
        self.a5_quota = a5_quota
        self.authority = authority
        self.roots = roots
        self._store = ProjectWorkspaceFiles(roots, max_file_bytes=max_file_bytes)
        self.max_file_bytes = max_file_bytes

    async def _confirm_read(
        self, invocation: ProjectInvocation, previous: ProjectPermit
    ) -> ProjectPermit:
        """Fence a long Files read against revoked/changed Project ownership."""
        current = await self.authority.require(invocation, "files.read")
        if (
            current.project_id != previous.project_id
            or current.actor_id != previous.actor_id
            or current.session_uuid != previous.session_uuid
            or current.project_access_revision != previous.project_access_revision
            or current.decision_version != previous.decision_version
            or current.project_owner_scope != previous.project_owner_scope
            or current.project_owner_id != previous.project_owner_id
        ):
            raise ProjectAccessDenied("FILE_PROJECT_ACCESS_STALE")
        return current

    async def provision(self, invocation: ProjectInvocation) -> None:
        permit = await self.authority.require(invocation, "files.manage")
        await asyncio.to_thread(self.roots.provision, permit)

    async def list(
        self,
        invocation: ProjectInvocation,
        path: str = "",
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> ProjectFilePage:
        permit = await self.authority.require(invocation, "files.read")
        result = await asyncio.to_thread(self._store.list, permit, path, offset=offset, limit=limit)
        await self._confirm_read(invocation, permit)
        return result

    async def info(self, invocation: ProjectInvocation, path: str) -> ProjectFileEntry:
        permit = await self.authority.require(invocation, "files.read")
        result = await asyncio.to_thread(self._store.info, permit, path)
        await self._confirm_read(invocation, permit)
        return result

    @asynccontextmanager
    async def open_snapshot(
        self,
        invocation: ProjectInvocation,
        path: str,
        *,
        chunk_bytes: int = 1024 * 1024,
    ) -> AsyncIterator[ProjectFileSnapshot]:
        permit = await self.authority.require(invocation, "files.read")
        task = asyncio.create_task(
            asyncio.to_thread(self._store.snapshot, permit, path, chunk_bytes=chunk_bytes)
        )
        try:
            snapshot = await asyncio.shield(task)
        except asyncio.CancelledError:
            # A thread cannot be canceled mid-copy; reclaim the anonymous fd
            # even when its caller has already disconnected/canceled.
            def discard_late_result(done: asyncio.Task[ProjectFileSnapshot]) -> None:
                if not done.cancelled() and done.exception() is None:
                    done.result().close()

            task.add_done_callback(discard_late_result)
            raise
        try:
            await self._confirm_read(invocation, permit)
            yield snapshot
        finally:
            snapshot.close()

    async def read_snapshot_chunk(
        self,
        invocation: ProjectInvocation,
        snapshot: ProjectFileSnapshot,
        *,
        offset: int,
        length: int,
    ) -> bytes:
        """Refresh Files read grants during long-lived Reverse upload sessions."""
        permit = await self.authority.require(invocation, "files.read")
        if (
            snapshot.project_id != permit.project_id
            or snapshot.actor_id != permit.actor_id
            or snapshot.agent_session_uuid != permit.session_uuid
            or snapshot.project_access_revision != permit.project_access_revision
            or snapshot.agent_session_version != permit.decision_version
        ):
            raise ProjectAccessDenied("FILE_SNAPSHOT_SCOPE_DENIED")
        content = await _drain_cancellable_file_io(snapshot.read_chunk, offset, length)
        await self._confirm_read(invocation, permit)
        return content

    async def sha256(self, invocation: ProjectInvocation, path: str) -> str:
        permit = await self.authority.require(invocation, "files.read")
        result = await asyncio.to_thread(self._store.sha256, permit, path)
        await self._confirm_read(invocation, permit)
        return result

    async def read(
        self, invocation: ProjectInvocation, path: str, *, max_bytes: int | None = None
    ) -> bytes:
        permit = await self.authority.require(invocation, "files.read")
        result = await asyncio.to_thread(self._store.read, permit, path, max_bytes=max_bytes)
        await self._confirm_read(invocation, permit)
        return result

    async def write_stream(
        self,
        invocation: ProjectInvocation,
        destination: str,
        chunks: AsyncIterator[bytes],
        *,
        create_parents: bool = False,
        expected_sha256: str = "",
        expected_size: int | None = None,
        operation_uuid: UUID | None = None,
    ) -> ProjectFileEntry:
        initial = await self.authority.require(invocation, "files.write")
        # Validate a canonical Project-relative namespace BEFORE taking a
        # durable quota reservation: the idempotency fingerprint must refer
        # to exactly the pathname that the descriptor-based store will open.
        destination = "/".join(_components(destination))
        upper_bound = self.max_file_bytes if expected_size is None else expected_size
        if type(upper_bound) is not int or not 0 <= upper_bound <= self.max_file_bytes:
            raise ProjectQuotaError("FILE_QUOTA_REQUEST_INVALID")
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_sha256)
        ):
            raise ProjectQuotaError("FILE_EXPECTED_SHA256_REQUIRED")
        if self.a5_quota is not None:
            if create_parents:
                # The A5 bytes ledger has no approved directory-inode quota
                # or transactionally fenced create-parent operation.
                raise A5FilesLedgerError("A5_FILE_PARENT_CREATION_UNAVAILABLE")
            if expected_size is None or not isinstance(operation_uuid, UUID):
                raise A5FilesLedgerError("A5_FILES_EXACT_SIZE_AND_UUID_REQUIRED")
            return await self._write_stream_a5(
                invocation,
                initial=initial,
                destination=destination,
                chunks=chunks,
                create_parents=create_parents,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                operation_uuid=operation_uuid,
            )
        reservation = await self.quota.reserve(
            initial,
            maximum_bytes=upper_bound,
            destination=destination,
            expected_sha256=expected_sha256,
            operation_uuid=operation_uuid,
        )
        task = asyncio.create_task(
            asyncio.to_thread(
                self._store.open_write_stage,
                initial,
                destination,
                create_parents=create_parents,
                expected_sha256=expected_sha256,
            )
        )
        try:
            stage = await asyncio.shield(task)
        except asyncio.CancelledError:

            def discard_late_stage(done: asyncio.Task[ProjectFileWriteStage]) -> None:
                if not done.cancelled() and done.exception() is None:
                    done.result().close()

            task.add_done_callback(discard_late_stage)
            await asyncio.shield(self.quota.release(reservation))
            raise
        except BaseException:
            await asyncio.shield(self.quota.release(reservation))
            raise
        try:
            offset = 0
            async for chunk in chunks:
                offset = await _drain_cancellable_file_io(stage.write_chunk, offset, chunk)
                if offset > reservation.requested_bytes:
                    raise ProjectQuotaError("FILE_QUOTA_RESERVATION_EXCEEDED")
            if expected_size is not None and offset != expected_size:
                raise ProjectQuotaError("FILE_SIZE_MISMATCH")
            # A long upload does not retain a revoked User/AgentSession grant.
            current = await self.authority.require(invocation, "files.write")
            if (
                current.project_access_revision != reservation.owner_revision
                or current.decision_version != initial.decision_version
                or current.actor_id != initial.actor_id
                or current.project_owner_scope != initial.project_owner_scope
                or current.project_owner_id != initial.project_owner_id
            ):
                raise ProjectQuotaError("FILE_QUOTA_OWNER_REVISION_STALE")
            self.quota.require_active(reservation)
            saved = await _drain_cancellable_file_io(stage.commit, current)
            await asyncio.shield(self.quota.finalize(reservation, count=saved.size_bytes))
            return saved
        finally:
            stage.close()
            if not stage.committed:
                await asyncio.shield(self.quota.release(reservation))

    async def _write_stream_a5(
        self,
        invocation: ProjectInvocation,
        *,
        initial: ProjectPermit,
        destination: str,
        chunks: AsyncIterator[bytes],
        create_parents: bool,
        expected_sha256: str,
        expected_size: int,
        operation_uuid: UUID,
    ) -> ProjectFileEntry:
        """Accepted A5 `reserve -> dispatch -> Files -> finalize` source flow.

        The Backend A5 ledger must mark DISPATCHED before any filesystem I/O.
        After dispatch no speculative release or retry is permitted. A lost
        acknowledgement freezes the operation for inspection/reconciliation.
        """
        flow = self.a5_quota
        assert flow is not None
        reserved = await flow.reserve(
            invocation,
            permit=initial,
            destination=destination,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            operation_uuid=operation_uuid,
        )
        dispatched = await flow.dispatch(invocation, permit=initial, reserved=reserved)
        task = asyncio.create_task(
            asyncio.to_thread(
                self._store.open_write_stage,
                initial,
                destination,
                create_parents=create_parents,
                expected_sha256=expected_sha256,
            )
        )
        try:
            stage = await asyncio.shield(task)
        except BaseException:

            def discard_late_stage(done: asyncio.Task[ProjectFileWriteStage]) -> None:
                if not done.cancelled() and done.exception() is None:
                    done.result().close()

            task.add_done_callback(discard_late_stage)
            # External staging outcome is unknown after cancellation; do not
            # release DISPATCHED bytes, even if a thread is still running.
            with suppress(Exception):
                await asyncio.shield(
                    flow.unknown(invocation, permit=initial, dispatched=dispatched)
                )
            raise
        try:
            offset = 0
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise A5FilesLedgerError("A5_FILE_CHUNK_NOT_BYTES")
                offset = await _drain_cancellable_file_io(stage.write_chunk, offset, chunk)
                if offset > expected_size:
                    raise A5FilesLedgerError("A5_FILE_SIZE_EXCEEDED")
            if offset != expected_size:
                raise A5FilesLedgerError("A5_FILE_SIZE_MISMATCH")
            current = await self.authority.require(invocation, "files.write")
            if (
                current.project_access_revision != initial.project_access_revision
                or current.decision_version != initial.decision_version
                or current.project_owner_scope != initial.project_owner_scope
                or current.project_owner_id != initial.project_owner_id
                or current.actor_id != initial.actor_id
                or current.session_uuid != initial.session_uuid
            ):
                raise A5FilesLedgerError("A5_FILE_ACCESS_CHANGED")
            if dispatched.expires_at <= datetime.now(UTC):
                raise A5FilesLedgerError("A5_FILE_RESERVATION_EXPIRED")
            saved = await _drain_cancellable_file_io(stage.commit, current)
            inode_digest = await _drain_cancellable_file_io(lambda: stage.observed_inode_digest)
            await flow.finalize(
                invocation,
                permit=initial,
                dispatched=dispatched,
                inode_digest=inode_digest,
                size=saved.size_bytes,
            )
            return saved
        except BaseException:
            # A5 backend `mark_unknown` can fail after commit too. In all
            # cases leave this write as an uncertain side effect for a trusted
            # Files inode/version observation, rather than automatic retry.
            with suppress(Exception):
                await asyncio.shield(
                    flow.unknown(invocation, permit=initial, dispatched=dispatched)
                )
            raise
        finally:
            # A slow OS worker cannot keep using a released staging FD:
            # `_drain_cancellable_file_io` already awaited each owned worker.
            stage.close()

    async def write(
        self,
        invocation: ProjectInvocation,
        path: str,
        contents: bytes,
        *,
        overwrite: bool = False,
        create_parents: bool = False,
        operation_uuid: UUID | None = None,
    ) -> ProjectFileEntry:
        if overwrite:
            raise ProjectQuotaError("FILE_QUOTA_OVERWRITE_UNAVAILABLE")
        if not isinstance(contents, bytes):
            raise ProjectQuotaError("FILE_CONTENT_INVALID")

        async def one_chunk() -> AsyncIterator[bytes]:
            yield contents

        return await self.write_stream(
            invocation,
            path,
            one_chunk(),
            create_parents=create_parents,
            expected_size=len(contents),
            expected_sha256=hashlib.sha256(contents).hexdigest(),
            operation_uuid=operation_uuid,
        )

    async def mkdir(
        self, invocation: ProjectInvocation, path: str, *, parents: bool = False
    ) -> None:
        if self.a5_quota is not None:
            raise A5FilesLedgerError("A5_DIRECTORY_QUOTA_UNAVAILABLE")
        permit = await self.authority.require(invocation, "files.write")
        await asyncio.to_thread(self._store.mkdir, permit, path, parents=parents)

    async def move(
        self,
        invocation: ProjectInvocation,
        source: str,
        destination: str,
        *,
        overwrite: bool = False,
    ) -> None:
        if self.a5_quota is not None:
            # A5 FileObject identity is keyed by path digest and DB version.
            # Rename without atomic FileObject metadata CAS would corrupt
            # byte accounting, expected revisions and reconciliation.
            raise A5FilesLedgerError("A5_FILE_MOVE_LEDGER_UNAVAILABLE")
        if overwrite:
            raise ProjectQuotaError("FILE_QUOTA_OVERWRITE_UNAVAILABLE")
        permit = await self.authority.require(invocation, "files.write")
        await asyncio.to_thread(self._store.move, permit, source, destination, overwrite=False)

    async def copy(
        self,
        invocation: ProjectInvocation,
        source: str,
        destination: str,
        *,
        overwrite: bool = False,
        operation_uuid: UUID | None = None,
    ) -> ProjectFileEntry:
        if overwrite:
            raise ProjectQuotaError("FILE_QUOTA_OVERWRITE_UNAVAILABLE")
        async with self.open_snapshot(invocation, source) as snapshot:

            async def chunks() -> AsyncIterator[bytes]:
                offset = 0
                while offset < snapshot.size_bytes:
                    part = await self.read_snapshot_chunk(
                        invocation, snapshot, offset=offset, length=1024 * 1024
                    )
                    if not part:
                        raise ProjectFileError("FILE_SNAPSHOT_TRUNCATED")
                    offset += len(part)
                    yield part

            return await self.write_stream(
                invocation,
                destination,
                chunks(),
                expected_size=snapshot.size_bytes,
                expected_sha256=snapshot.sha256,
                operation_uuid=operation_uuid,
            )

    async def cleanup_orphan_uploads(
        self,
        invocation: ProjectInvocation,
        path: str = "",
        *,
        older_than_seconds: float = 3600.0,
        limit: int = 128,
    ) -> int:
        permit = await self.authority.require(invocation, "files.manage")
        return await asyncio.to_thread(
            self._store.cleanup_orphan_uploads,
            permit,
            path,
            older_than_seconds=older_than_seconds,
            limit=limit,
        )

    async def delete(self, invocation: ProjectInvocation, path: str) -> None:
        # Deleting a charged file/directory requires durable quota release,
        # expected filesystem revision and Project retention policy. None is
        # accepted in C1-B2, so even a source-injected files.manage permit
        # cannot silently destroy data while leaving accounting incorrect.
        await self.authority.require(invocation, "files.manage")
        if not isinstance(path, str) or not path.strip():
            raise ProjectQuotaError("FILE_PATH_REQUIRED")
        raise ProjectQuotaError("FILE_DELETE_LIFECYCLE_UNAVAILABLE")
