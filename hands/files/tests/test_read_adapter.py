"""Focused consumer checks; no real grant, user token or filesystem read.

Real ProjectFilesService is used for deny/cancel integration. A recording
subclass below exercises only bounded result and immutable-argument wiring;
it supplies fixture bytes, never a Cedar Permit or native read acceptance.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import patch
from uuid import uuid4

from files_hand._read_adapter import (
    FilesMcpReadUnavailable,
    FilesReadArguments,
    FilesReadContent,
    UnmountedFilesReadEffect,
)

from modules.files.a6_signed import A6SignedFilesFlow
from modules.files.project_files import ProjectFilesService
from modules.project_runtime import (
    ProjectAction,
    ProjectInvocation,
    ProjectOperationScope,
    ProjectPermit,
    ProjectRootRegistry,
    ProjectRuntimeAuthority,
)


def check_arguments() -> None:
    bad = (
        None,
        {},
        [],
        {"path": ""},
        {"path": "."},
        {"path": ".."},
        {"path": "../secret"},
        {"path": "/var/run/secrets"},
        {"path": "a//b"},
        {"path": "dir/./file"},
        {"path": "a\\b"},
        {"path": "a\x00b"},
        {"path": "a\ud800"},
        {"path": "line\nbreak"},
        {"path": "a" * 256},
        {"path": "é" * 128},
        {"path": "a/" * 64 + "b"},
        {"path": "file", "max_bytes": False},
        {"path": "file", "max_bytes": 0},
        {"path": "file", "max_bytes": 262145},
        {"path": "file", "max_bytes": 2.0},
        {"path": "file", "max_bytes": "16"},
        {"path": "file", "grant": True},
        {"path": "file", "project_uuid": "untrusted-selector"},
        {"path": ".upload-" + "a" * 32 + ".tmp"},
        {"path": "e\u0301.txt"},
    )
    for arguments in bad:
        try:
            FilesReadArguments.parse(arguments)
        except FilesMcpReadUnavailable:
            pass
        else:
            raise AssertionError("untrusted read input accepted")
    # Direct construction must not skip the parser's path or byte budget.
    for path, budget in (("../secret", 1), ("file", True), ("file", 262145)):
        try:
            FilesReadArguments(path=path, max_bytes=budget)
        except FilesMcpReadUnavailable:
            pass
        else:
            raise AssertionError("unsafe internal read DTO accepted")
    request = FilesReadArguments.parse({"path": "документы/отчёт.bin"})
    wire = request.canonical_arguments()
    assert wire == {"path": request.path, "max_bytes": 262_144}
    wire["path"] = "another-file"
    assert request.path == "документы/отчёт.bin"
    assert FilesReadArguments.parse({"path": "%2e%2e/literal"}).path == "%2e%2e/literal"
    for payload in (b"", b"\x00\xffunit-fixture", b"x" * 262_144):
        result = FilesReadContent.from_verified_bytes(request, payload)
        assert base64.b64decode(result.content_base64, validate=True) == payload
        assert result.sha256 == hashlib.sha256(payload).hexdigest()
        assert result.size_bytes == len(payload)
        assert "content_base64=" not in repr(result)
        # The Frontend's current read-result decoder accepts exactly this
        # shape; no Cedar/credential/owner private diagnostics belong here.
        wire = result.content_payload()
        assert set(wire) == {"path", "size_bytes", "sha256", "content_base64"}
        assert wire["path"] == request.path
        assert wire["size_bytes"] == len(payload)
        assert wire["sha256"] == hashlib.sha256(payload).hexdigest()
        assert base64.b64decode(wire["content_base64"], validate=True) == payload
        assert "access_token" not in wire and "resource_revision" not in wire
    for payload in (bytearray(b"x"), "not-bytes", b"x" * 262_145):
        try:
            FilesReadContent.from_verified_bytes(request, cast(bytes, payload))
        except FilesMcpReadUnavailable as exc:
            assert exc.code == "FILES_READ_RESULT_INVALID"
        else:
            raise AssertionError("invalid/oversized result accepted")


def unverified_invocation(action: ProjectAction = "files.read") -> ProjectInvocation:
    # Shape only: these objects are intentionally NOT authentic evidence.
    # The real unconfigured authority below must refuse them before I/O.
    project, session = uuid4(), uuid4()
    return ProjectInvocation(
        project_id=project,
        session_uuid=session,
        caller_evidence=object(),
        service_evidence=object(),
        operation_scope=ProjectOperationScope(
            project_id=project,
            agent_session_uuid=session,
            action=action,
            request_uuid=uuid4(),
            fingerprint="0" * 64,
        ),
    )


def real_service(authority: ProjectRuntimeAuthority) -> ProjectFilesService:
    # Constructor only: no directory is created, opened, or provisioned.
    return ProjectFilesService(
        authority,
        ProjectRootRegistry(Path("/not-accessed-files-read-probe")),
        max_file_bytes=262_144,
        a6_quota=A6SignedFilesFlow(authority),
    )


async def check_real_service_denies() -> None:
    invocation = unverified_invocation()
    service = real_service(ProjectRuntimeAuthority())
    effect = UnmountedFilesReadEffect(files=service)
    with patch.object(service._store, "read") as disk:
        try:
            await effect.execute(invocation=invocation, arguments={"path": "file.txt"})
        except FilesMcpReadUnavailable as exc:
            assert exc.code == "FILES_READ_AUTHORIZATION_UNAVAILABLE"
            assert str(exc) == exc.code and exc.__cause__ is None
        else:
            raise AssertionError("real service granted access without an authority")
        disk.assert_not_called()
    for incoming in (None, object(), "unverified"):
        try:
            await effect.execute(
                invocation=cast(ProjectInvocation | None, incoming), arguments={"path": "file"}
            )
        except FilesMcpReadUnavailable as exc:
            assert exc.code == "FILES_READ_TRUSTED_OWNER_REQUIRED"
        else:
            raise AssertionError("unverified invocation accepted")
    for context in (
        replace(invocation, operation_scope=None),
        unverified_invocation("files.write"),
    ):
        with patch.object(service, "read") as owner_read:
            try:
                await effect.execute(invocation=context, arguments={"path": "file"})
            except FilesMcpReadUnavailable as exc:
                assert exc.code == "FILES_READ_SIGNED_INVOCATION_REQUIRED"
            else:
                raise AssertionError("incorrect operation scope accepted")
            owner_read.assert_not_called()
    try:
        UnmountedFilesReadEffect(files=cast(ProjectFilesService, object()))
    except ValueError:
        pass
    else:
        raise AssertionError("untrusted owner class accepted")
    print("REAL_FILES_SERVICE_DENIES_BEFORE_FILESYSTEM_PASS")


async def check_cancel() -> None:
    class WaitingAccess:
        def __init__(self) -> None:
            self.entered = asyncio.Event()

        async def authorize(
            self, invocation: ProjectInvocation, action: ProjectAction
        ) -> ProjectPermit:
            assert invocation is not None and action == "files.read"
            self.entered.set()
            await asyncio.Event().wait()
            raise AssertionError("no Permit is ever returned by this fixture")

    authority = WaitingAccess()
    service = real_service(ProjectRuntimeAuthority(authority))
    effect = UnmountedFilesReadEffect(files=service)
    with patch.object(service._store, "read") as disk:
        operation = asyncio.create_task(
            effect.execute(invocation=unverified_invocation(), arguments={"path": "file"})
        )
        await asyncio.wait_for(authority.entered.wait(), 2)
        operation.cancel()
        try:
            await operation
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation was swallowed or returned bytes")
        disk.assert_not_called()
    print("REAL_FILES_SERVICE_CANCELLATION_PROPAGATES_PASS")


async def check_wiring_only() -> None:
    class RecordingService(ProjectFilesService):
        # Test double solely for forwarding/response envelope, no filesystem.
        def __init__(self) -> None:
            self.entered, self.release = asyncio.Event(), asyncio.Event()
            self.failure: Exception | None = None
            self.seen: tuple[ProjectInvocation, str, int | None] | None = None

        async def read(
            self, invocation: ProjectInvocation, path: str, *, max_bytes: int | None = None
        ) -> bytes:
            self.seen = invocation, path, max_bytes
            self.entered.set()
            await self.release.wait()
            if self.failure is not None:
                raise self.failure
            return b"fixture"

    owner, context = RecordingService(), unverified_invocation()
    effect = UnmountedFilesReadEffect(files=owner)
    incoming: dict[str, object] = {"path": "folder/original", "max_bytes": 7}
    operation = asyncio.create_task(effect.execute(invocation=context, arguments=incoming))
    await asyncio.wait_for(owner.entered.wait(), 2)
    incoming.update(path="different-file", max_bytes=262_144)
    owner.release.set()
    reply = await operation
    assert owner.seen == (context, "folder/original", 7)
    assert reply.path == "folder/original" and reply.size_bytes == 7
    for failure in (OSError("private-owner-detail"), TimeoutError("private-owner-detail")):
        owner.failure = failure
        try:
            await effect.execute(invocation=context, arguments={"path": "file"})
        except FilesMcpReadUnavailable as exc:
            assert exc.code == "FILES_READ_AUTHORIZATION_UNAVAILABLE"
            assert "private-owner-detail" not in str(exc)
        else:
            raise AssertionError("owner failure returned file contents")
    print("FIXTURE_ONLY_IMMUTABLE_ARGUMENTS_AND_REDACTED_FAILURE_PASS")


async def main() -> None:
    check_arguments()
    await check_real_service_denies()
    await check_cancel()
    await check_wiring_only()
    print("FILES_READ_CONSUMER_CHECKS_PASS_NOT_A_PERMIT_OR_MCP_ACCEPTANCE")


if __name__ == "__main__":
    asyncio.run(main())
