"""Actual private temp-FS confinement + fixture-only owner lifecycle checks.

No real Rauthy login, current Project grant, private C2 peer or MCP read
is supplied. Passing these checks cannot authorize a deployed read.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from files_hand._fd_snapshot import (
    FilesReadObservation,
    HeldFilesRead,
    observe_root,
    open_confined_read,
)
from files_hand._native_read import NativeFilesReadRequest, UnmountedNativeFilesRead
from files_hand._read_adapter import FilesMcpReadUnavailable, FilesReadArguments

from modules.project_runtime import ProjectFileError

PROJECT = UUID("12345678-1234-4234-8234-123456789abc")
SESSION = UUID("12345678-1234-4234-8234-123456789abd")
REQUEST = UUID("12345678-1234-4234-8234-123456789abe")


def expected_error(call: Callable[[], object]) -> None:
    try:
        call()
    except (ProjectFileError, FilesMcpReadUnavailable, OSError):
        return
    raise AssertionError("unsafe native filesystem input accepted")


def filesystem_checks(root: Path, fd: int) -> None:
    folder = root / "nested"
    folder.mkdir(mode=0o700)
    target = folder / "data.bin"
    original = b"\x00\xffnative-files-fixture"
    target.write_bytes(original)
    target.chmod(0o600)
    request = FilesReadArguments("nested/data.bin", 128)
    stamp = observe_root(fd)
    before_fds = len(os.listdir("/proc/self/fd"))
    for _ in range(40):
        held = open_confined_read(fd, stamp, request)
        try:
            assert held.payload == original
            held.validate_current()
            assert "native-files-fixture" not in repr(held)
        finally:
            held.close()
            held.close()
        assert held.payload == b""
    assert len(os.listdir("/proc/self/fd")) == before_fds
    # Mutations include SAME-LENGTH content changes and namespace rebinding.
    held = open_confined_read(fd, stamp, request)
    target.write_bytes(b"x" * len(original))
    expected_error(held.validate_current)
    held.close()
    target.write_bytes(original)
    held = open_confined_read(fd, observe_root(fd), request)
    folder.rename(root / "previous")
    folder.mkdir(mode=0o700)
    target.write_bytes(original)
    target.chmod(0o600)
    expected_error(held.validate_current)
    held.close()
    # The re-opened file is a different inode despite identical payload.
    target.chmod(0o644)
    expected_error(lambda: open_confined_read(fd, observe_root(fd), request))
    target.chmod(0o600)
    os.link(target, folder / "linked")
    expected_error(lambda: open_confined_read(fd, observe_root(fd), request))
    (folder / "linked").unlink()
    (folder / "symlink").symlink_to(target)
    (root / "directory-link").symlink_to(folder, target_is_directory=True)
    os.mkfifo(folder / "pipe", mode=0o600)
    for path in ("nested/symlink", "directory-link/data.bin", "nested/pipe", "nested"):
        expected_error(
            lambda p=path: open_confined_read(fd, observe_root(fd), FilesReadArguments(p, 128))
        )
    expected_error(
        lambda: open_confined_read(fd, observe_root(fd), FilesReadArguments(request.path, 2))
    )
    assert len(os.listdir("/proc/self/fd")) == before_fds
    print("REAL_TEMP_FS_BYTES_CONFINEMENT_REPLACEMENT_MODE_LINK_FIFO_FD_CHECKS_PASS")


class ScopeFixture:
    def __init__(self, request: NativeFilesReadRequest, fd: int, mode: str = "pass") -> None:
        self.request = request
        self.root_fd = fd
        self.root_observation = observe_root(fd)
        self.owner_revision = 1
        self.expires_at = datetime.now(UTC) + timedelta(seconds=4)
        self.mode = mode
        self.revalidated = False
        self.final_expiry: datetime | None = None

    async def revalidate(self, observation: FilesReadObservation) -> bool | None:
        assert observation.root == self.root_observation
        self.revalidated = True
        self.final_expiry = datetime.now(UTC) + timedelta(seconds=4)
        if self.mode == "final_expired":
            self.final_expiry = datetime.now(UTC) - timedelta(seconds=1)
        if self.mode == "missing_final":
            self.final_expiry = None
        if self.mode in {"deny", "suppress_denial"}:
            raise RuntimeError("/private/fixture/details")
        if self.mode == "boolean":
            return True
        if self.mode == "stall":
            await asyncio.Event().wait()
        if self.mode == "revision":
            self.owner_revision += 1
        if self.mode == "expiry":
            self.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        return None


class AuthorityFixture:
    def __init__(self, fd: int, mode: str = "pass", target: Path | None = None) -> None:
        self.fd, self.mode = fd, mode
        self.target = target
        self.exited = False
        self.scope = None

    @asynccontextmanager
    async def open_read(self, request: NativeFilesReadRequest) -> AsyncIterator[ScopeFixture]:
        if self.mode == "entry_deny":
            raise RuntimeError("no actual authority fixture")
        self.scope = ScopeFixture(request, self.fd, self.mode)
        if self.mode == "wrong_request":
            self.scope.request = replace(request, expected_grant_revision=2)
        if self.mode == "excessive_lease":
            self.scope.expires_at = datetime.now(UTC) + timedelta(seconds=6)
        if self.mode == "initial_expiry":
            self.scope.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if self.mode == "wrong_root":
            self.scope.root_observation = replace(self.scope.root_observation, inode=0)
        try:
            yield self.scope
        except RuntimeError:
            if self.mode != "suppress_denial":
                raise
        finally:
            self.exited = True
        if self.mode == "exit_deny":
            raise RuntimeError("revocation at the final owner barrier")
        if self.mode == "exit_expiry":
            self.scope.final_expiry = datetime.now(UTC) - timedelta(seconds=1)
        if self.mode == "exit_change":
            assert self.target is not None
            await asyncio.to_thread(self.target.write_bytes, b"changed-during-exit")


async def contract_checks(root: Path, fd: int) -> None:
    request = NativeFilesReadRequest(
        REQUEST, PROJECT, SESSION, 1, FilesReadArguments("nested/data.bin", 128)
    )
    assert (
        request.request_fingerprint
        != replace(request, arguments=FilesReadArguments("nested/data.bin", 64)).request_fingerprint
    )
    assert (
        request.request_fingerprint
        != replace(request, expected_grant_revision=2).request_fingerprint
    )
    assert (
        request.request_fingerprint
        != replace(request, agent_session_uuid=PROJECT).request_fingerprint
    )
    try:
        await UnmountedNativeFilesRead().execute(request)
    except FilesMcpReadUnavailable as exc:
        assert exc.code == "FILES_NATIVE_AUTHORITY_UNAVAILABLE"
    else:
        raise AssertionError("unconfigured native read ran")

    target = root / "nested/data.bin"
    target.write_bytes(b"fixture-payload")
    target.chmod(0o600)
    for mode in (
        "entry_deny",
        "wrong_request",
        "initial_expiry",
        "excessive_lease",
        "wrong_root",
        "deny",
        "suppress_denial",
        "boolean",
        "revision",
        "expiry",
        "exit_deny",
        "exit_expiry",
        "exit_change",
        "missing_final",
        "final_expired",
    ):
        target.write_bytes(b"fixture-payload")
        port = AuthorityFixture(fd, mode, target)
        try:
            await UnmountedNativeFilesRead(port).execute(request)
        except FilesMcpReadUnavailable as exc:
            assert exc.code == "FILES_NATIVE_READ_UNAVAILABLE"
            assert "private" not in str(exc)
        else:
            raise AssertionError(f"{mode}: data escaped owner denial")
    target.write_bytes(b"fixture-payload")
    port = AuthorityFixture(fd)
    result = await UnmountedNativeFilesRead(port).execute(request)
    assert base64.b64decode(result.content_base64) == b"fixture-payload"
    assert port.scope.revalidated and port.exited
    print("FIXTURE_ONLY_NATIVE_OWNER_BEFORE_AFTER_EXIT_DENIAL_AND_BINDING_PASS")

    # A canceled thread may finish its read, but data cannot be returned and
    # its descriptors must be reclaimed BEFORE the owner context is exited.
    entered, release = threading.Event(), threading.Event()
    counts = len(os.listdir("/proc/self/fd"))

    def blocked(*args: object) -> HeldFilesRead:
        entered.set()
        assert release.wait(3)
        return open_confined_read(*args)

    port = AuthorityFixture(fd)
    with patch("files_hand._native_read.open_confined_read", side_effect=blocked):
        task = asyncio.create_task(UnmountedNativeFilesRead(port).execute(request))
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        task.cancel()
        await asyncio.sleep(0.01)
        assert not port.exited
        task.cancel()
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("canceled read returned payload")
    assert port.exited and len(os.listdir("/proc/self/fd")) == counts
    print("NATIVE_READ_CANCELLATION_DRAINS_WORKER_BEFORE_OWNER_EXIT_PASS")
    port = AuthorityFixture(fd, "stall")
    with patch("files_hand._native_read._OWNER_SCOPE_TIMEOUT", 0.05):
        try:
            await UnmountedNativeFilesRead(port).execute(request)
        except FilesMcpReadUnavailable as exc:
            assert exc.code == "FILES_NATIVE_READ_UNAVAILABLE"
        else:
            raise AssertionError("timed-out authority returned bytes")
    assert port.exited and len(os.listdir("/proc/self/fd")) == counts
    print("NATIVE_OWNER_TIMEOUT_NO_BYTES_OR_FD_LEAK_PASS")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="briareus-files-native-") as temporary:
        root = Path(temporary)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            filesystem_checks(root, fd)
            asyncio.run(contract_checks(root, fd))
        finally:
            os.close(fd)
    print("NO_REAL_OAUTH_ACCESS_RECEIPT_OR_MCP_FILE_TOOL_CLAIMED")


if __name__ == "__main__":
    main()
