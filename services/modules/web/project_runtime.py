"""Unmounted Briareus Web→Files transfer and protected Browser trust gate.

All Project file effects require the exact signed A6 FilesQuota-v2 operation.
No R6 local browser lease, global profile, inherited process environment or
external user's Chrome process is adopted as a trusted RuntimeSession owner.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from modules.files._attachment_transport import open_public_attachment
from modules.files.project_files import ProjectFilesService, _drain_cancellable_file_io
from modules.files.project_workspace import ProjectFileEntry
from modules.project_runtime import (
    ProjectInvocation,
    ProjectRuntimeAuthority,
)


@dataclass(frozen=True, slots=True)
class IsolatedBrowserProfile:
    """Trusted factory attestation, not proof of OS isolation by itself.

    The injected `InternalBrowserFactory` must be an approved browser process
    manager before this unmounted adapter is ever enabled. A shared Browser
    profile, cookie jar, downloads folder or cache is not a Project sandbox.
    """

    project_id: UUID
    context_uuid: UUID
    profile_uuid: UUID
    profile_isolated: bool
    cookies_isolated: bool
    cache_isolated: bool
    downloads_project_scoped: bool
    host_browser_unmodified: bool


@dataclass(frozen=True, slots=True)
class RemoteBrowserAttachment:
    """User-owned Chrome: consent and connection identity, NEVER process kill."""

    project_id: UUID
    attachment_uuid: UUID
    consent_verified: bool
    operator_browser_owned: bool
    process_termination_forbidden: bool


class InternalProjectBrowser(Protocol):
    """Owns one Project's private Chromium context/profile, not a shared tab."""

    project_id: UUID
    context_uuid: UUID
    isolation: IsolatedBrowserProfile

    async def close_owned_context(self) -> None: ...


class InternalBrowserFactory(Protocol):
    async def open_isolated(self, *, project_id: UUID) -> InternalProjectBrowser: ...


class RemoteProjectBrowser(Protocol):
    """An attached external user's Chrome; never destroy its native process."""

    project_id: UUID
    attachment_uuid: UUID
    ownership: RemoteBrowserAttachment

    async def disconnect(self) -> None: ...


class RemoteBrowserConnector(Protocol):
    async def attach(self, *, project_id: UUID) -> RemoteProjectBrowser: ...


class ProjectWebRuntimeUnavailable(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProjectWebRuntime:
    """Stateless external HTTPS transfer, no Browser OS/process ownership."""

    def __init__(
        self,
        *,
        authority: ProjectRuntimeAuthority,
        files: ProjectFilesService,
    ) -> None:
        self.authority = authority
        self.files = files

    async def require_browser_owner(
        self,
        invocation: ProjectInvocation,
        *,
        mode: Literal["managed", "remote"],
    ) -> None:
        if mode not in {"managed", "remote"}:
            raise ProjectWebRuntimeUnavailable("PROJECT_BROWSER_MODE_INVALID")
        await self.authority.require(
            invocation, "web.internal" if mode == "managed" else "web.remote"
        )
        # A9 has not accepted the signed owner nonce. An internal Chromium
        # needs an attested Project-only UID/mount/profile/cgroup worker; a
        # remote user Chrome needs a verified consent-bound transport owner.
        # Neither can use an in-memory R6 lease or global CDP/browser profile.
        raise ProjectWebRuntimeUnavailable("PROJECT_BROWSER_SIGNED_OWNER_UNAVAILABLE")

    async def download_public_https(
        self,
        invocation: ProjectInvocation,
        *,
        url: str,
        destination: str,
        expected_size: int,
        expected_sha256: str,
        operation_uuid: UUID,
        max_seconds: float = 600.0,
        chunk_bytes: int = 65536,
    ) -> ProjectFileEntry:
        """Public pinned HTTPS into A6 Files, using one durable write UUID.

        This is not an HTTP/MCP route. A separate signed Files service+human
        proof must validate each quota/dispatch/storage/commit effect; no
        credential-bearing HTTP response or proxy URL is forwarded to Files.
        """
        if (
            not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= 600.0
            or type(chunk_bytes) is not int
            or not 0 < chunk_bytes <= 262144
            or type(expected_size) is not int
            or not 0 <= expected_size <= min(self.files.max_file_bytes, 262144)
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_sha256)
        ):
            raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_DOWNLOAD_INVALID")
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.action != "files.write"
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
            or scope.request_uuid != operation_uuid
        ):
            raise ProjectWebRuntimeUnavailable("PROJECT_FILES_SIGNED_OPERATION_REQUIRED")
        # Check the current caller/grant BEFORE opening any external socket.
        await self.authority.require(invocation, "files.write")
        deadline = time.monotonic() + max_seconds
        try:
            response = await _drain_cancellable_file_io(open_public_attachment, url)
        except Exception as exc:
            raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_EGRESS_UNAVAILABLE") from exc
        try:
            lengths = response.headers.get_all("Content-Length", [])
            if len(lengths) > 1:
                raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_LENGTH_AMBIGUOUS")
            if lengths:
                try:
                    actual = int(lengths[0])
                except ValueError as exc:
                    raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_LENGTH_INVALID") from exc
                if actual != expected_size:
                    raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_LENGTH_MISMATCH")

            async def chunks() -> AsyncIterator[bytes]:
                digest = hashlib.sha256()
                count = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_DEADLINE_EXCEEDED")
                    piece = await _drain_cancellable_file_io(response.read, chunk_bytes)
                    if time.monotonic() >= deadline:
                        raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_DEADLINE_EXCEEDED")
                    if not piece:
                        break
                    count += len(piece)
                    if count > expected_size:
                        raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_TOO_LARGE")
                    digest.update(piece)
                    yield piece
                if count != expected_size or digest.hexdigest() != expected_sha256:
                    raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_CHECKSUM_MISMATCH")

            return await self.files.write_stream(
                invocation,
                destination,
                chunks(),
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                operation_uuid=operation_uuid,
            )
        finally:
            # A canceled caller may leave a worker performing a blocking TLS
            # read; _drain_cancellable_file_io shields its FD lifecycle.
            await _drain_cancellable_file_io(response.__exit__, None, None, None)

    async def save_http_download(
        self,
        invocation: ProjectInvocation,
        destination: str,
        content: bytes,
        *,
        operation_uuid: UUID,
    ) -> ProjectFileEntry:
        """Selected bounded content is still an independently signed write."""
        return await self.files.write(
            invocation,
            destination,
            content,
            overwrite=False,
            create_parents=False,
            operation_uuid=operation_uuid,
        )

    async def save_http_download_stream(
        self,
        invocation: ProjectInvocation,
        destination: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        expected_sha256: str,
        operation_uuid: UUID,
    ) -> ProjectFileEntry:
        """No speculative byte size, idempotency fallback or raw key env."""
        return await self.files.write_stream(
            invocation,
            destination,
            chunks,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            operation_uuid=operation_uuid,
        )
