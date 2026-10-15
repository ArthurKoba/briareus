"""Clock fault fixtures plus actual temporary-file IO; no system clock changes."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from files_hand import _lease_deadline, _native_read
from files_hand._fd_snapshot import (
    FilesReadObservation,
    HeldFilesRead,
    observe_root,
    open_confined_read,
)
from files_hand._lease_deadline import ReadLeaseDeadline
from files_hand._read_adapter import FilesMcpReadUnavailable, FilesReadArguments


class ClockType(type):
    def __instancecheck__(cls, value: object) -> bool:
        return isinstance(value, datetime)


class FixtureClock(metaclass=ClockType):
    current = datetime.now(UTC)

    @classmethod
    def now(cls, _tz: object = None) -> datetime:
        return cls.current


async def clock_case(fd: int, mode: str) -> None:
    request = _native_read.NativeFilesReadRequest(
        uuid4(), uuid4(), uuid4(), 1, FilesReadArguments("file", 128)
    )
    count = len(os.listdir("/proc/self/fd"))
    FixtureClock.current = datetime.now(UTC)
    elapsed = [100.0]

    class Scope:
        def __init__(self) -> None:
            self.request = request
            self.root_fd = fd
            self.root_observation = observe_root(fd)
            self.owner_revision = 1
            self.expires_at = FixtureClock.current + timedelta(seconds=0.4)
            self.final_expiry: datetime | None = None

        async def revalidate(self, _observation: FilesReadObservation) -> None:
            self.final_expiry = self.expires_at
            if mode == "forward_jump":
                FixtureClock.current += timedelta(seconds=1)

    class Authority:
        @asynccontextmanager
        async def open_read(
            self, _request: _native_read.NativeFilesReadRequest
        ) -> AsyncIterator[Scope]:
            yield Scope()
            if mode == "expired_during_exit":
                elapsed[0] += 1
                FixtureClock.current -= timedelta(seconds=0.25)

    def reader(root_fd: int, root: object, args: FilesReadArguments) -> HeldFilesRead:
        elapsed[0] += 1 if mode == "expired_during_read" else 0.05
        if mode == "expired_during_read":
            FixtureClock.current -= timedelta(seconds=0.25)
        return open_confined_read(root_fd, root, args)

    with (
        patch.object(_native_read, "datetime", FixtureClock),
        patch.object(_lease_deadline, "datetime", FixtureClock),
        patch.object(_lease_deadline, "time", SimpleNamespace(monotonic=lambda: elapsed[0])),
        patch.object(_native_read, "open_confined_read", reader),
    ):
        try:
            result = await _native_read.UnmountedNativeFilesRead(Authority()).execute(request)
        except FilesMcpReadUnavailable:
            assert mode != "pass", mode
        else:
            assert mode == "pass" and result.size_bytes == 7
    assert len(os.listdir("/proc/self/fd")) == count


async def main(fd: int) -> None:
    for mode in ("pass", "expired_during_read", "expired_during_exit", "forward_jump"):
        await clock_case(fd, mode)

    FixtureClock.current = datetime.now(UTC)
    elapsed = [100.0]
    with (
        patch.object(_lease_deadline, "datetime", FixtureClock),
        patch.object(_lease_deadline, "time", SimpleNamespace(monotonic=lambda: elapsed[0])),
    ):
        lease = ReadLeaseDeadline.capture(
            FixtureClock.current + timedelta(seconds=3), maximum_seconds=5
        )
        lease.check()
        FixtureClock.current -= timedelta(seconds=30)
        elapsed[0] = 104
        try:
            lease.check()
        except FilesMcpReadUnavailable:
            pass
        else:
            raise AssertionError("clock rollback renewed original lease")
    print("FILES_UTC_AND_ELAPSED_DEADLINES_READ_EXIT_AND_CLOCK_ROLLBACK_PASS")
    print("REAL_TEMP_FILE_NO_FD_LEAK_TIMES_AND_OWNER_SCOPE_ARE_CONTROLLED_FIXTURES")


with tempfile.TemporaryDirectory(prefix="files-lease-check-") as directory:
    root = Path(directory)
    (root / "file").write_bytes(b"fixture")
    (root / "file").chmod(0o600)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        asyncio.run(main(descriptor))
    finally:
        os.close(descriptor)
