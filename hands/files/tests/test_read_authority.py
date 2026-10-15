"""Concrete scope orchestration on real temp files; trust/owner replies fixtures."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from files_hand._fd_snapshot import observe_root
from files_hand._native_read import NativeFilesReadRequest, UnmountedNativeFilesRead
from files_hand._read_adapter import FilesMcpReadUnavailable, FilesReadArguments
from files_hand._read_authority import BoundFilesReadAuthority, PrivateReadReply

PROJECT = UUID("12345678-1234-4234-8234-123456789abc")
SESSION = UUID("12345678-1234-4234-8234-123456789abd")
OPERATION = UUID("12345678-1234-4234-8234-123456789abe")
ACTOR = UUID("12345678-1234-4234-8234-123456789abf")


class ChannelFixture:
    def __init__(self, request: NativeFilesReadRequest, mode: str) -> None:
        self.request = request
        self.request_fingerprint = request.request_fingerprint
        self.actor_uuid = ACTOR
        self.expires_at = datetime.now(UTC) + timedelta(seconds=30)
        self.phases: list[str] = []
        self.mode = mode

    async def decide(self, *, body: bytes, effect_key: str) -> PrivateReadReply:
        assert effect_key == self.request.selector.effect_key
        wire = json.loads(body)
        self.phases.append(wire["phase"])
        assert wire["expected_resource_revision"] == 7
        now = datetime.now(UTC)
        reply = {
            "protocol": "files-read-decision-v1",
            "allowed": True,
            "operation_uuid": wire["operation_uuid"],
            "phase": wire["phase"],
            "actor_uuid": str(ACTOR),
            "project_uuid": wire["project_uuid"],
            "agent_session_uuid": wire["agent_session_uuid"],
            "hand": "files",
            "tool": "read_file",
            "action": "files.read",
            "resource": wire["resource"],
            "grant_revision": wire["expected_grant_revision"],
            "resource_revision": 7,
            "max_bytes": wire["max_bytes"],
            "checked_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=4)).isoformat(),
        }
        if self.mode == "core_outage_before" and wire["phase"] == "before_read":
            raise ConnectionError("fixture Core/Access unavailable")
        if self.mode == "core_outage_after" and wire["phase"] == "after_read":
            raise ConnectionError("fixture Core/Access unavailable")
        if wire["phase"] == "after_read":
            if self.mode == "revoked":
                return PrivateReadReply(403, b"{}")
            if self.mode == "wrong_actor":
                reply["actor_uuid"] = str(PROJECT)
            if self.mode == "changed_revision":
                reply["resource_revision"] = 8
            if self.mode == "changed_request":
                reply["max_bytes"] += 1
            if self.mode == "caller_mutated":
                self.actor_uuid = PROJECT
            if self.mode == "expired":
                reply["expires_at"] = now.isoformat()
            if self.mode == "extra_fields":
                reply["root"] = "/not-a-caller-root"
        return PrivateReadReply(200, json.dumps(reply).encode())


class ChannelsFixture:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.channel: ChannelFixture | None = None
        self.exited = False

    @asynccontextmanager
    async def open_channel(self, request: NativeFilesReadRequest) -> AsyncIterator[ChannelFixture]:
        if self.mode == "unverified":
            raise ValueError("signed caller not verified")
        self.channel = ChannelFixture(request, self.mode)
        if self.mode == "wrong_fingerprint":
            self.channel.request_fingerprint = "0" * 64
        try:
            yield self.channel
        except ValueError:
            if self.mode != "suppress_root_denial":
                raise
        finally:
            self.exited = True
        if self.mode == "channel_exit_deny":
            raise ValueError("caller revoked at exit")


class RootFixture:
    def __init__(self, request: NativeFilesReadRequest, fd: int, mode: str) -> None:
        self.request_fingerprint = request.request_fingerprint
        self.project_uuid = request.project_uuid
        self.owner_revision = 7
        self.root_fd = fd
        self.root_observation = observe_root(fd)
        self.expires_at = datetime.now(UTC) + timedelta(seconds=30)
        self.checks = 0
        self.mode = mode

    async def validate_current(self) -> None:
        self.checks += 1
        if self.mode == "mapping_replaced" and self.checks > 2:
            self.owner_revision = 8
        if self.mode == "mapping_revoked" and self.checks > 2:
            raise ValueError("mapping revoked")


class RootsFixture:
    def __init__(self, root: Path, mode: str) -> None:
        self.root, self.mode = root, mode
        self.held = False
        self.exited = False

    @asynccontextmanager
    async def hold_root(
        self, *, request: NativeFilesReadRequest, actor_uuid: UUID
    ) -> AsyncIterator[RootFixture]:
        assert actor_uuid == ACTOR
        self.held = True
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        lease = RootFixture(request, descriptor, self.mode)
        if self.mode == "foreign_root":
            lease.project_uuid = SESSION
        try:
            yield lease
        finally:
            os.close(descriptor)
            lease.root_fd = -1  # Closed port must not be queried as live later.
            self.exited = True
        if self.mode in {"root_exit_deny", "suppress_root_denial"}:
            raise ValueError("mapping invalid at exit")


async def exercise(root: Path) -> None:
    args = FilesReadArguments("data.txt", 128)
    request = NativeFilesReadRequest(OPERATION, PROJECT, SESSION, 4, args)
    try:
        await UnmountedNativeFilesRead(BoundFilesReadAuthority()).execute(request)
    except FilesMcpReadUnavailable:
        pass
    else:
        raise AssertionError("unconfigured ports granted a read")
    modes = (
        "pass",
        "unverified",
        "core_outage_before",
        "core_outage_after",
        "wrong_fingerprint",
        "foreign_root",
        "revoked",
        "wrong_actor",
        "changed_revision",
        "changed_request",
        "caller_mutated",
        "expired",
        "extra_fields",
        "mapping_replaced",
        "mapping_revoked",
        "root_exit_deny",
        "channel_exit_deny",
        "suppress_root_denial",
    )
    baseline = len(os.listdir("/proc/self/fd"))
    for mode in modes:
        channels = ChannelsFixture(mode)
        roots = RootsFixture(root, mode)
        adapter = BoundFilesReadAuthority(channels=channels, roots=roots)
        try:
            result = await UnmountedNativeFilesRead(adapter).execute(request)
        except FilesMcpReadUnavailable:
            assert mode != "pass", mode
        else:
            assert mode == "pass", mode
            assert base64.b64decode(result.content_base64) == b"real temporary fixture bytes"
            assert channels.channel is not None
            assert channels.channel.phases == ["before_read", "after_read"]
        if mode in {"unverified", "wrong_fingerprint"}:
            assert not roots.held
        elif roots.held:
            assert roots.exited
        assert len(os.listdir("/proc/self/fd")) == baseline, mode
    print(f"BOUND_FILES_AUTHORITY_{len(modes)}_SCENARIOS_NO_FD_LEAK_PASS")
    print("CORE_ACCESS_OUTAGE_BEFORE_AND_AFTER_FILES_READ_FAIL_CLOSED_PASS")
    print("NO_REAL_SIGNED_CALLER_OR_MAPPING_AUTHORITY_ASSERTED")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="files-bound-ports-") as temporary:
        root = Path(temporary)
        path = root / "data.txt"
        path.write_bytes(b"real temporary fixture bytes")
        path.chmod(0o600)
        asyncio.run(exercise(root))


if __name__ == "__main__":
    main()
