"""Bounded Files read DTOs and retained unmounted legacy A6 consumer.

The legacy ProjectOwnerFence cannot be synthesized from a Rauthy V2
allow response. The independent native successor is in _native_read;
neither consumer is registered while actual owner authority is absent.

This module is NOT registered in FastMCP or the public Gateway. It prepares
the minimal concrete read shape for the first real Files effect, without
accepting caller-created User/Project/AgentSession grants or opening paths.

The injected ProjectFilesService owns the genuine A6 signed Files read,
per-effect ProjectRuntimeAuthority/Cedar access, native project-root FD,
and post-read revocation fence. Missing independent owner transport cannot
be papered over by this adapter or its unit tests.
"""

from __future__ import annotations

import base64
import hashlib
import unicodedata
from dataclasses import dataclass, field

from modules.files.a6_signed import A6FilesUnavailable, canonical_files_path
from modules.files.project_files import ProjectFilesService
from modules.project_runtime import ProjectFileError, ProjectInvocation, ProjectOperationScope

_MAX_READ_BYTES = 262_144
_MAX_RELATIVE_PATH_BYTES = 4096


class FilesMcpReadUnavailable(Exception):
    """Public failure code only; never an owner error or filesystem path."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class FilesReadArguments:
    """Only a relative file path and a bounded byte budget are caller input."""

    path: str
    max_bytes: int

    def __post_init__(self) -> None:
        # A direct internal constructor must enforce the same contract as
        # untrusted JSON parsing. This also keeps output encoding bounded.
        if (
            not isinstance(self.path, str)
            or not 1 <= len(self.path) <= _MAX_RELATIVE_PATH_BYTES
            or not unicodedata.is_normalized("NFC", self.path)
            or type(self.max_bytes) is not int
            or not 1 <= self.max_bytes <= _MAX_READ_BYTES
        ):
            raise FilesMcpReadUnavailable("FILES_READ_ARGUMENTS_INVALID")
        try:
            canonical = canonical_files_path(self.path)
            if canonical != self.path:
                raise ValueError("noncanonical file path")
        except (ProjectFileError, A6FilesUnavailable, ValueError, UnicodeError):
            raise FilesMcpReadUnavailable("FILES_READ_PATH_INVALID") from None

    @classmethod
    def parse(cls, arguments: object) -> FilesReadArguments:
        if not isinstance(arguments, dict) or set(arguments) not in (
            {"path"},
            {"path", "max_bytes"},
        ):
            raise FilesMcpReadUnavailable("FILES_READ_ARGUMENTS_INVALID")
        return cls(path=arguments["path"], max_bytes=arguments.get("max_bytes", _MAX_READ_BYTES))

    def canonical_arguments(self) -> dict[str, object]:
        """Materialize defaults for a future owner resolver BEFORE its PDP call.

        A fresh dictionary cannot mutate this frozen request. Neither the
        dictionary nor this dataclass provides identity or resource authority.
        """
        return {"path": self.path, "max_bytes": self.max_bytes}


@dataclass(frozen=True, slots=True)
class FilesReadContent:
    """Only bounded verified bytes become an MCP JSON-safe response.

    This structure is NOT a grant, owner evidence, read witness or signed
    receipt. It must be constructed only AFTER the owner read completes.
    """

    path: str
    size_bytes: int
    sha256: str
    content_base64: str = field(repr=False)

    def content_payload(self) -> dict[str, str | int]:
        """Exact bounded JSON shape for a FUTURE owner-authenticated BFF.

        Calling this does not authorize a read or expose a public route:
        the native owner must first complete both Access phases, the Files
        mapping check and the post-read FD validation. In particular, do
        not serialize this from raw MCP or browser-submitted DTOs.
        """
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "content_base64": self.content_base64,
        }

    @classmethod
    def from_verified_bytes(cls, request: FilesReadArguments, payload: bytes) -> FilesReadContent:
        if (
            not isinstance(request, FilesReadArguments)
            or type(payload) is not bytes
            or len(payload) > request.max_bytes
        ):
            raise FilesMcpReadUnavailable("FILES_READ_RESULT_INVALID")
        return cls(
            path=request.path,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            content_base64=base64.b64encode(payload).decode("ascii"),
        )


class UnmountedFilesReadEffect:
    """One future read effect, never a public tool or a Permit issuer.

    Supervisor may inject an already-verified Files owner service. It MUST
    independently provide an authenticated ProjectInvocation bearing a
    current service-human delegation and original signed operation_scope.
    No HTTP headers, project_id, actor_id or bearer are read from MCP JSON.
    """

    def __init__(self, *, files: ProjectFilesService | None = None) -> None:
        if files is not None and not isinstance(files, ProjectFilesService):
            raise ValueError("trusted ProjectFilesService owner required")
        self._files = files

    async def execute(
        self, *, invocation: ProjectInvocation | None, arguments: object
    ) -> FilesReadContent:
        files = self._files
        if files is None or not isinstance(invocation, ProjectInvocation):
            raise FilesMcpReadUnavailable("FILES_READ_TRUSTED_OWNER_REQUIRED")
        scope = invocation.operation_scope
        if (
            not isinstance(scope, ProjectOperationScope)
            or invocation.project_id.version != 4
            or scope.action != "files.read"
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
        ):
            raise FilesMcpReadUnavailable("FILES_READ_SIGNED_INVOCATION_REQUIRED")
        request = FilesReadArguments.parse(arguments)
        # No filesystem IO here. The real Files service will check Project
        # permit + A6 signed read, descriptor confinement, then recheck
        # Project owner before returning any payload.
        try:
            payload = await files.read(invocation, request.path, max_bytes=request.max_bytes)
        except Exception:
            # Current-owner SQL/OS/transport failures, timeouts and revoke
            # denials all return one public error. Never leak private paths,
            # provider reasons, raw filesystem errors or witness metadata.
            # asyncio.CancelledError is a BaseException and still propagates.
            raise FilesMcpReadUnavailable("FILES_READ_AUTHORIZATION_UNAVAILABLE") from None
        return FilesReadContent.from_verified_bytes(request, payload)
