"""Actual configured Project-directory opens; mapping and caller are fixtures."""

from __future__ import annotations

import asyncio
import base64
import errno
import os
import shutil
import tempfile
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from files_hand import _root_registry
from files_hand._native_read import NativeFilesReadRequest, UnmountedNativeFilesRead
from files_hand._read_adapter import FilesMcpReadUnavailable, FilesReadArguments
from files_hand._read_authority import BoundFilesReadAuthority
from files_hand._root_registry import RegistryFilesRootPort
from test_read_authority import ACTOR, OPERATION, PROJECT, SESSION, ChannelsFixture

from modules.project_runtime.workspace_roots import ProjectFileError, ProjectRootRegistry


class MappingFixture:
    def __init__(self, request: NativeFilesReadRequest, mode: str) -> None:
        self.request_fingerprint = request.request_fingerprint
        self.actor_uuid = ACTOR
        self.project_uuid = request.project_uuid
        self.resource_revision = 7
        self.expires_at = datetime.now(UTC) + timedelta(seconds=20)
        self.mode, self.checks = mode, 0
        if mode == "wrong_actor":
            self.actor_uuid = PROJECT
        if mode == "foreign_project":
            self.project_uuid = SESSION
        if mode == "invalid_revision":
            self.resource_revision = False
        if mode == "stale":
            self.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    async def validate_current(self) -> None:
        self.checks += 1
        if self.mode == "changed_revision" and self.checks > 3:
            self.resource_revision += 1
        if self.mode == "revoked" and self.checks > 3:
            raise ValueError("fixture current mapping revoked")
        if self.mode == "core_mapping_unavailable" and self.checks > 3:
            raise ConnectionError("fixture Core mapping unavailable")


class MappingsFixture:
    def __init__(self, mode: str = "pass") -> None:
        self.mode = mode

    @asynccontextmanager
    async def hold_mapping(
        self, *, request: NativeFilesReadRequest, actor_uuid: UUID
    ) -> AsyncIterator[MappingFixture]:
        assert actor_uuid == ACTOR
        mapping = MappingFixture(request, self.mode)
        try:
            yield mapping
        except ValueError:
            if self.mode != "suppress_body":
                raise
        if self.mode == "exit_deny":
            raise ValueError("fixture mapping exit refused")
        if self.mode == "exit_expired":
            mapping.expires_at = datetime.now(UTC) - timedelta(seconds=1)


async def main(base: Path) -> None:
    request = NativeFilesReadRequest(
        OPERATION, PROJECT, SESSION, 4, FilesReadArguments("data", 128)
    )
    folder = base / str(PROJECT)
    folder.mkdir(mode=0o700)
    (folder / "data").write_bytes(b"real configured namespace fixture")
    (folder / "data").chmod(0o600)
    baseline = len(os.listdir("/proc/self/fd"))
    for mode in (
        "pass",
        "wrong_actor",
        "foreign_project",
        "invalid_revision",
        "stale",
        "changed_revision",
        "revoked",
        "core_mapping_unavailable",
        "exit_deny",
    ):
        port = RegistryFilesRootPort(base_root=base, mappings=MappingsFixture(mode))
        reader = UnmountedNativeFilesRead(
            BoundFilesReadAuthority(channels=ChannelsFixture("pass"), roots=port)
        )
        try:
            result = await reader.execute(request)
        except FilesMcpReadUnavailable:
            assert mode != "pass", mode
        else:
            assert mode == "pass", mode
            assert base64.b64decode(result.content_base64) == b"real configured namespace fixture"
        assert len(os.listdir("/proc/self/fd")) == baseline, mode
    print("ACTUAL_REGISTRY_NATIVE_BOUND_READ_MAPPING_FIXTURES_PASS")
    # Constructor/expiry refusal after the real opener acquired FDs may
    # not leak the underlying storage base or Project descriptor.
    port = RegistryFilesRootPort(base_root=base, mappings=MappingsFixture())
    with patch.object(
        _root_registry,
        "_RegistryRootLease",
        side_effect=FilesMcpReadUnavailable("FILES_OWNER_AUTHORITY_EXPIRED"),
    ):
        try:
            async with port.hold_root(request=request, actor_uuid=ACTOR):
                raise AssertionError("expired lease entered")
        except FilesMcpReadUnavailable:
            pass
    assert len(os.listdir("/proc/self/fd")) == baseline
    print("ROOT_LEASE_CONSTRUCTION_DENIAL_CLOSES_ALREADY_OPEN_DESCRIPTORS_PASS")

    missing = RegistryFilesRootPort(base_root=base / "not_created")
    try:
        async with missing.hold_root(request=request, actor_uuid=ACTOR):
            raise AssertionError("unconfigured mapping permitted")
    except FilesMcpReadUnavailable:
        pass
    assert not (base / "not_created").exists()

    for mode in (
        "renamed_project",
        "renamed_base",
        "symlink_project",
        "public_mode",
        "suppress_body",
    ):
        temporary = Path(tempfile.mkdtemp(prefix="files-root-change-"))
        namespace = temporary / "base"
        namespace.mkdir(mode=0o700)
        project = namespace / str(PROJECT)
        project.mkdir(mode=0o700)
        port = RegistryFilesRootPort(base_root=namespace, mappings=MappingsFixture(mode))
        try:
            try:
                async with port.hold_root(request=request, actor_uuid=ACTOR) as lease:
                    if mode == "renamed_project":
                        project.rename(namespace / "previous")
                        project.mkdir(mode=0o700)
                    elif mode == "renamed_base":
                        namespace.rename(temporary / "previous")
                        namespace.mkdir(mode=0o700)
                        (namespace / str(PROJECT)).mkdir(mode=0o700)
                    elif mode == "symlink_project":
                        project.rename(namespace / "previous")
                        project.symlink_to(namespace / "previous", target_is_directory=True)
                    elif mode == "public_mode":
                        project.chmod(0o755)
                    elif mode == "suppress_body":
                        raise ValueError("fixture suppressed body refusal")
                    await lease.validate_current()
            except (FilesMcpReadUnavailable, ProjectFileError):
                pass
            except OSError as exc:
                assert mode == "symlink_project" and exc.errno in {
                    errno.ENOTDIR,
                    errno.ELOOP,
                    errno.EXDEV,
                }, (mode, exc.errno)
            else:
                raise AssertionError("changed namespace escaped validation: " + mode)
            assert len(os.listdir("/proc/self/fd")) == baseline, mode
        finally:
            # This routine owns this uniquely created test tree only.
            shutil.rmtree(temporary)
    print("REGISTRY_ROOT_REPLACEMENT_BASE_RENAME_SYMLINK_MODE_AND_SUPPRESSION_DENIED")
    # Cancel while the real OS opener has already acquired descriptors.
    # The thread must finish and close those descriptors before exit.
    started, release = threading.Event(), threading.Event()
    original_open = _root_registry._open_project

    def delayed_open(
        registry: ProjectRootRegistry, project: UUID
    ) -> _root_registry._HeldProjectRoot:
        handle = original_open(registry, project)
        started.set()
        release.wait(2)
        return handle

    port = RegistryFilesRootPort(base_root=base, mappings=MappingsFixture())

    async def acquire() -> None:
        async with port.hold_root(request=request, actor_uuid=ACTOR):
            raise AssertionError("canceled root acquisition entered scope")

    with patch.object(_root_registry, "_open_project", delayed_open):
        operation = asyncio.create_task(acquire())
        try:
            assert await asyncio.to_thread(started.wait, 1)
            operation.cancel()
            await asyncio.sleep(0.01)
            operation.cancel()
            assert not operation.done()
            release.set()
            try:
                await operation
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("root acquisition swallowed cancellation")
        finally:
            release.set()
    assert len(os.listdir("/proc/self/fd")) == baseline
    print("ROOT_ACQUISITION_CANCEL_DRAINS_REAL_WORKER_AND_CLOSES_DESCRIPTORS_PASS")
    print("NO_DIRECTORY_PROVISION_NO_FD_LEAK_NO_REAL_MAPPING_AUTHORITY_CLAIM")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="files-native-registry-") as root:
        asyncio.run(main(Path(root)))
