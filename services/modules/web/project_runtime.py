"""Private Project Web adapters: stateless HTTP files and independent browser leases.

Only a service-authenticated Project authorizer may enable these adapters.
The existing Web MCP `browser_*`, `devtools_*` and `external_*` tools are NOT
re-mounted here: their current global profile and remote policy are legacy.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from modules.files._attachment_transport import open_public_attachment
from modules.files.project_files import ProjectFilesService, _drain_cancellable_file_io
from modules.files.project_workspace import ProjectFileEntry
from modules.project_runtime import (
    ProjectInvocation,
    ProjectPermit,
    ProjectRootRegistry,
    ProjectRuntimeAuthority,
    RuntimeLease,
    RuntimeLeaseRegistry,
)
from modules.project_runtime.runtime_owner import ProjectRuntimeOwner


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
    def __init__(
        self,
        *,
        authority: ProjectRuntimeAuthority,
        roots: ProjectRootRegistry,
        files: ProjectFilesService,
        leases: RuntimeLeaseRegistry,
        internal_factory: InternalBrowserFactory | None = None,
        remote_connector: RemoteBrowserConnector | None = None,
        owner: ProjectRuntimeOwner | None = None,
    ) -> None:
        self.authority = authority
        self.roots = roots
        self.files = files
        self.leases = leases
        self._internal_factory = internal_factory
        self._remote_connector = remote_connector
        self._owner = owner
        # Generation tokens prevent a stale cleanup callback from closing a
        # new context that happens to reuse the same provider-defined UUID.
        self._context_owners: dict[UUID, tuple[UUID, UUID]] = {}
        self._profile_owners: dict[UUID, tuple[UUID, UUID]] = {}
        self._attachment_owners: dict[UUID, tuple[UUID, UUID]] = {}
        self._owner_lock = asyncio.Lock()

    def _require_owner(self) -> ProjectRuntimeOwner:
        if self._owner is None:
            raise ProjectWebRuntimeUnavailable("PROJECT_DURABLE_LEASE_UNAVAILABLE")
        self._owner.require_available()
        return self._owner

    async def _check_root(self, permit: ProjectPermit) -> None:
        # Verify the configured owner-controlled root, never a guessed path.
        def open_without_access() -> None:
            with self.roots.open(permit):
                pass

        await asyncio.to_thread(open_without_access)

    async def open_internal(
        self,
        invocation: ProjectInvocation,
        *,
        idle_seconds: float,
        hard_seconds: float,
    ) -> RuntimeLease:
        owner = self._require_owner()
        if self._internal_factory is None:
            raise ProjectWebRuntimeUnavailable("PROJECT_BROWSER_ISOLATION_UNAVAILABLE")
        permit = await self.authority.require(invocation, "web.internal")
        await self._check_root(permit)
        browser = await self._internal_factory.open_isolated(project_id=permit.project_id)
        attested = browser.isolation
        if (
            browser.project_id != permit.project_id
            or not isinstance(browser.context_uuid, UUID)
            or browser.context_uuid.version != 4
            or not isinstance(attested, IsolatedBrowserProfile)
            or attested.project_id != permit.project_id
            or attested.context_uuid != browser.context_uuid
            or not isinstance(attested.profile_uuid, UUID)
            or attested.profile_uuid.version != 4
            or not all(
                (
                    attested.profile_isolated is True,
                    attested.cookies_isolated is True,
                    attested.cache_isolated is True,
                    attested.downloads_project_scoped is True,
                    attested.host_browser_unmodified is True,
                )
            )
        ):
            # A foreign context is not ours to destroy, even during rejection.
            raise ProjectWebRuntimeUnavailable("PROJECT_BROWSER_PROFILE_UNVERIFIED")
        generation = uuid4()
        owned = (permit.project_id, generation)
        async with self._owner_lock:
            if (
                browser.context_uuid in self._context_owners
                or attested.profile_uuid in self._profile_owners
            ):
                raise ProjectWebRuntimeUnavailable("PROJECT_BROWSER_CONTEXT_OR_PROFILE_REUSED")
            self._context_owners[browser.context_uuid] = owned
            self._profile_owners[attested.profile_uuid] = owned
        cleanup_lock = asyncio.Lock()

        async def close_context() -> None:
            # Both the owner failure path and lease reaper may request cleanup.
            # Serialize against overlapping callback invocations, while a
            # stale generation must never close a replacement browser.
            async with cleanup_lock:
                async with self._owner_lock:
                    if self._context_owners.get(browser.context_uuid) != owned:
                        return
                await browser.close_owned_context()
                # Failed cleanup keeps the generation reserved for reconcile.
                async with self._owner_lock:
                    if self._context_owners.get(browser.context_uuid) == owned:
                        del self._context_owners[browser.context_uuid]
                    if self._profile_owners.get(attested.profile_uuid) == owned:
                        del self._profile_owners[attested.profile_uuid]

        try:
            return await owner.open(
                permit,
                kind="internal_browser",
                idle_seconds=idle_seconds,
                hard_seconds=hard_seconds,
                cleanup=close_context,
            )
        except BaseException:
            await close_context()
            raise

    async def open_remote(
        self,
        invocation: ProjectInvocation,
        *,
        idle_seconds: float,
        hard_seconds: float,
    ) -> RuntimeLease:
        owner = self._require_owner()
        if self._remote_connector is None:
            raise ProjectWebRuntimeUnavailable("PROJECT_REMOTE_BROWSER_UNAVAILABLE")
        permit = await self.authority.require(invocation, "web.remote")
        await self._check_root(permit)
        attachment = await self._remote_connector.attach(project_id=permit.project_id)
        ownership = attachment.ownership
        if (
            attachment.project_id != permit.project_id
            or not isinstance(attachment.attachment_uuid, UUID)
            or attachment.attachment_uuid.version != 4
            or not isinstance(ownership, RemoteBrowserAttachment)
            or ownership.project_id != permit.project_id
            or ownership.attachment_uuid != attachment.attachment_uuid
            or ownership.consent_verified is not True
            or ownership.operator_browser_owned is not True
            or ownership.process_termination_forbidden is not True
        ):
            # Do not disconnect or terminate an attachment owned by another
            # Project/browser. Consent is an approved connector's attestation,
            # not a checkbox supplied by a remote MCP user.
            raise ProjectWebRuntimeUnavailable("PROJECT_REMOTE_OWNER_UNVERIFIED")
        generation = uuid4()
        owned = (permit.project_id, generation)
        async with self._owner_lock:
            if attachment.attachment_uuid in self._attachment_owners:
                raise ProjectWebRuntimeUnavailable("PROJECT_REMOTE_ATTACHMENT_REUSED")
            self._attachment_owners[attachment.attachment_uuid] = owned
        cleanup_lock = asyncio.Lock()

        async def disconnect_attachment() -> None:
            # This callback NEVER closes the user's actual Chrome/profile.
            async with cleanup_lock:
                async with self._owner_lock:
                    if self._attachment_owners.get(attachment.attachment_uuid) != owned:
                        return
                await attachment.disconnect()
                # A failed disconnect stays reserved, not reassigned.
                async with self._owner_lock:
                    if self._attachment_owners.get(attachment.attachment_uuid) == owned:
                        del self._attachment_owners[attachment.attachment_uuid]

        try:
            return await owner.open(
                permit,
                kind="remote_browser",
                idle_seconds=idle_seconds,
                hard_seconds=hard_seconds,
                cleanup=disconnect_attachment,
            )
        except BaseException:
            await disconnect_attachment()
            raise

    async def attach(
        self,
        invocation: ProjectInvocation,
        runtime_session_uuid: UUID,
        *,
        remote: bool = False,
    ) -> RuntimeLease:
        permit = await self.authority.require(
            invocation, "web.remote" if remote else "web.internal"
        )
        return await self._require_owner().attach(permit, runtime_session_uuid)

    async def close(
        self,
        invocation: ProjectInvocation,
        runtime_session_uuid: UUID,
        *,
        expected_revision: int,
        remote: bool = False,
    ) -> RuntimeLease:
        permit = await self.authority.require(
            invocation, "web.remote" if remote else "web.internal"
        )
        return await self._require_owner().close(
            permit, runtime_session_uuid, expected_revision=expected_revision
        )

    async def mark_transport_lost(
        self,
        invocation: ProjectInvocation,
        runtime_session_uuid: UUID,
        *,
        expected_revision: int,
        remote: bool = False,
    ) -> RuntimeLease:
        permit = await self.authority.require(
            invocation, "web.remote" if remote else "web.internal"
        )
        return await self._require_owner().mark_lost(
            permit, runtime_session_uuid, expected_revision=expected_revision
        )

    async def reconnect_remote(
        self,
        invocation: ProjectInvocation,
        lost_session_uuid: UUID,
        *,
        expected_revision: int,
        idle_seconds: float,
        hard_seconds: float,
    ) -> RuntimeLease:
        """Explicit recovery with a NEW lease, never implicit command replay.

        First verify that the old remote MCP attachment was disconnected.
        If cleanup is uncertain, refuse a second attachment. External Chrome
        itself is intentionally preserved across both operations.
        """
        permit = await self.authority.require(invocation, "web.remote")
        closed = await self._require_owner().cleanup_lost(
            permit, lost_session_uuid, expected_revision=expected_revision
        )
        if closed.state != "closed":
            raise ProjectWebRuntimeUnavailable("PROJECT_REMOTE_CLEANUP_UNCERTAIN")
        return await self.open_remote(
            invocation, idle_seconds=idle_seconds, hard_seconds=hard_seconds
        )

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
        chunk_bytes: int = 1024 * 1024,
    ) -> ProjectFileEntry:
        """Safely fetch public HTTPS into this Project's transactional Files.

        Private unmounted operation. No client-provided proxy, workspace root
        or auth cookie can be set. The legacy attachment egress validates each
        HTTPS redirect, public target IP and original-host TLS. Files owns
        quota, SHA staging, current Project rights and atomic commit.
        """
        if (
            not 0 < max_seconds <= 600.0
            or not 0 < chunk_bytes <= 1024 * 1024
            or type(expected_size) is not int
            or not 0 <= expected_size <= self.files.max_file_bytes
            or not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_DOWNLOAD_INVALID")
        await self.authority.require(invocation, "files.write")
        deadline = time.monotonic() + max_seconds
        try:
            response = await _drain_cancellable_file_io(open_public_attachment, url)
        except Exception as exc:
            raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_EGRESS_UNAVAILABLE") from exc
        try:
            declared = response.headers.get_all("Content-Length", [])
            if len(declared) > 1:
                raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_LENGTH_AMBIGUOUS")
            if declared:
                try:
                    content_length = int(declared[0])
                except ValueError as exc:
                    raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_LENGTH_INVALID") from exc
                if content_length != expected_size:
                    raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_LENGTH_MISMATCH")

            async def chunks() -> AsyncIterator[bytes]:
                digest = hashlib.sha256()
                total = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_DEADLINE_EXCEEDED")
                    block = await _drain_cancellable_file_io(response.read, chunk_bytes)
                    if time.monotonic() >= deadline:
                        raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_DEADLINE_EXCEEDED")
                    if not block:
                        break
                    total += len(block)
                    if total > expected_size:
                        raise ProjectWebRuntimeUnavailable("PROJECT_HTTP_TOO_LARGE")
                    digest.update(block)
                    yield block
                if total != expected_size or digest.hexdigest() != expected_sha256:
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
            await _drain_cancellable_file_io(response.__exit__, None, None, None)

    async def save_http_download(
        self,
        invocation: ProjectInvocation,
        destination: str,
        content: bytes,
        *,
        overwrite: bool = False,
        operation_uuid: UUID | None = None,
    ) -> ProjectFileEntry:
        """Stateless curl download, with its own Files write authorization."""
        return await self.files.write(
            invocation,
            destination,
            content,
            overwrite=overwrite,
            create_parents=False,
            operation_uuid=operation_uuid,
        )

    async def save_http_download_stream(
        self,
        invocation: ProjectInvocation,
        destination: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_sha256: str = "",
        operation_uuid: UUID | None = None,
    ) -> ProjectFileEntry:
        """Stateless curl data into bounded, atomic Project Files staging.

        Existing Web tools are not switched to this method until C1-B/C2;
        the provider never receives arbitrary filesystem or Terminal access.
        """
        return await self.files.write_stream(
            invocation,
            destination,
            chunks,
            expected_sha256=expected_sha256,
            operation_uuid=operation_uuid,
        )
