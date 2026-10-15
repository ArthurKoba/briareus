"""Parse public MCP selectors for a future Files read; confer NO authority.

The returned request is only a bounded, canonical command descriptor.
A real signed Rauthy resource verifier, independently authenticated Files
channel, current owner root and two-phase Access/Cedar decision are required
before UnmountedNativeFilesRead may expose bytes. This module does not
register read_file or open filesystem paths.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from starlette.requests import Request

from ._native_read import NativeFilesReadRequest
from ._read_adapter import FilesMcpReadUnavailable, FilesReadArguments

_PROJECT_HEADER = "x-briareus-project-uuid"
_SESSION_HEADER = "x-briareus-agent-session-uuid"
_REVISION_HEADER = "x-briareus-grant-revision"
_MAX_REVISION = 2**63 - 1


def _canonical_uuid_header(request: Request, name: str) -> UUID:
    values = request.headers.getlist(name)
    if len(values) != 1 or not 1 <= len(values[0]) <= 36:
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
    raw = values[0]
    try:
        value = UUID(raw)
    except (TypeError, ValueError, AttributeError):
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID") from None
    if value.version != 4 or str(value) != raw:
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
    return value


def _canonical_revision_header(request: Request) -> int:
    values = request.headers.getlist(_REVISION_HEADER)
    if len(values) != 1:
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
    raw = values[0]
    if not 1 <= len(raw) <= 19 or not raw.isascii() or not raw.isdecimal():
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
    revision = int(raw)
    if not 1 <= revision <= _MAX_REVISION or str(revision) != raw:
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
    return revision


def stage_untrusted_native_read(
    *,
    request: Request,
    arguments: object,
) -> NativeFilesReadRequest:
    """Canonicalize only selectors; never bind them to an OAuth actor.

    Caller-controlled Project/AgentSession/revision remain untrusted even
    if Gateway forwarded them. The generated operation UUID prevents an
    MCP caller from selecting or replaying the private read operation.
    No serialized client request may supply the token, actor, root or port.
    """
    if (
        not isinstance(request, Request)
        or request.method != "POST"
        or request.url.path != "/mcp"
        or request.scope.get("raw_path") != b"/mcp"
        or request.scope.get("query_string", b"") != b""
        or request.headers.getlist("cookie")
    ):
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
    credentials = request.headers.getlist("authorization")
    if len(credentials) != 1:
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
    bearer = credentials[0]
    if (
        not bearer.startswith("Bearer ")
        or len(bearer) > 8192
        or bearer.count(" ") != 1
        or not bearer[7:]
        or any(char.isspace() for char in bearer[7:])
    ):
        raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
    # This is only a syntax prerequisite. The SDK + trusted private
    # channel MUST independently verify that signed bearer and scope.
    args = FilesReadArguments.parse(arguments)
    return NativeFilesReadRequest(
        request_uuid=uuid4(),
        project_uuid=_canonical_uuid_header(request, _PROJECT_HEADER),
        agent_session_uuid=_canonical_uuid_header(request, _SESSION_HEADER),
        expected_grant_revision=_canonical_revision_header(request),
        arguments=args,
    )
