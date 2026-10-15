"""Private Files selector staging; never an authenticated read or Cedar Permit."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from files_hand._mcp_request import stage_untrusted_native_read
from files_hand._native_read import UnmountedNativeFilesRead
from files_hand._read_adapter import FilesMcpReadUnavailable
from files_hand._read_decision import FilesReadDecisionRequest
from starlette.requests import Request

_PROJECT = "12345678-1234-4234-8234-123456789abc"
_SESSION = "12345678-1234-4234-8234-123456789abd"
_BEARER = b"Bearer opaque_fixture_not_a_signed_resource_token"
_HEADERS: list[tuple[bytes, bytes]] = [
    (b"authorization", _BEARER),
    (b"x-briareus-project-uuid", _PROJECT.encode()),
    (b"x-briareus-agent-session-uuid", _SESSION.encode()),
    (b"x-briareus-grant-revision", b"7"),
]


def request(
    headers: list[tuple[bytes, bytes]],
    *,
    method: str = "POST",
    path: str = "/mcp",
    raw_path: bytes | None = None,
    query: bytes = b"",
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode() if raw_path is None else raw_path,
            "headers": headers,
            "query_string": query,
            "scheme": "http",
            "server": ("briareus-files", 8000),
        }
    )


def expect_rejected(
    headers: list[tuple[bytes, bytes]],
    arguments: object,
    *,
    method: str = "POST",
    path: str = "/mcp",
    raw_path: bytes | None = None,
    query: bytes = b"",
) -> None:
    try:
        stage_untrusted_native_read(
            request=request(headers, method=method, path=path, raw_path=raw_path, query=query),
            arguments=arguments,
        )
    except FilesMcpReadUnavailable:
        pass
    else:
        raise AssertionError("invalid/untrusted Files MCP selector accepted")


async def main() -> None:
    arguments = {"path": "src/doc.txt", "max_bytes": 4096}
    staged = stage_untrusted_native_read(request=request(_HEADERS), arguments=arguments)
    assert staged.project_uuid == UUID(_PROJECT) and staged.agent_session_uuid == UUID(_SESSION)
    assert staged.expected_grant_revision == 7
    assert staged.arguments.path == arguments["path"] and staged.arguments.max_bytes == 4096
    assert len(staged.selector.resource_id) == 117
    assert staged.selector.effect_key.startswith('["files","read_file","workspace_path",')
    assert staged.request_uuid.version == 4
    second = stage_untrusted_native_read(request=request(_HEADERS), arguments=arguments)
    assert second.request_uuid != staged.request_uuid
    assert second.request_fingerprint != staged.request_fingerprint
    assert second.selector.effect_key == staged.selector.effect_key
    for phase in ("before_read", "after_read"):
        body = json.loads(FilesReadDecisionRequest(staged, 11, phase).wire_body())
        assert body["operation_uuid"] == str(staged.request_uuid)
        assert body["resource"] == staged.selector.decision_resource()
        assert body["expected_resource_revision"] == 11
        assert body["expected_grant_revision"] == 7
        assert body["phase"] == phase
        assert body["action"] == "files.read" and body["tool"] == "read_file"
    arguments["path"] = "altered-client-input"
    assert staged.arguments.path == "src/doc.txt"

    for instance in (staged, second):
        # A syntactically valid request still has NO trustworthy caller, root
        # or private Access peer. It cannot return bytes or register read_file.
        try:
            await UnmountedNativeFilesRead().execute(instance)
        except FilesMcpReadUnavailable as exc:
            assert exc.code == "FILES_NATIVE_AUTHORITY_UNAVAILABLE"
        else:
            raise AssertionError("untrusted selectors produced Files contents")

    expect_rejected(_HEADERS, {"path": "src/doc.txt", "project_uuid": _PROJECT})
    expect_rejected(_HEADERS, {"path": "../other"})
    expect_rejected(_HEADERS, {"path": "/etc/passwd"})
    expect_rejected(_HEADERS, {"path": "src/doc.txt", "max_bytes": True})
    expect_rejected(_HEADERS, {"path": "src/doc.txt", "max_bytes": 262145})
    expect_rejected(_HEADERS, {"path": "src/doc.txt"}, method="GET")
    expect_rejected(_HEADERS, {"path": "src/doc.txt"}, path="/health/live")
    expect_rejected(_HEADERS, {"path": "src/doc.txt"}, raw_path=b"/%6dcp")
    expect_rejected(_HEADERS, {"path": "src/doc.txt"}, raw_path=b"/mcp/.")
    expect_rejected(_HEADERS, {"path": "src/doc.txt"}, query=b"actor_uuid=forged")
    expect_rejected([*_HEADERS, (b"cookie", b"session=fake")], {"path": "src/doc.txt"})
    expect_rejected([*_HEADERS, (b"authorization", _BEARER)], {"path": "src/doc.txt"})
    expect_rejected(
        [(n, v) for n, v in _HEADERS if n != b"authorization"],
        {"path": "src/doc.txt"},
    )
    expect_rejected(
        [(n, v) for n, v in _HEADERS if n != b"authorization"]
        + [(b"authorization", b"Basic invalid")],
        {"path": "src/doc.txt"},
    )
    for name, values in (
        (b"x-briareus-project-uuid", [b"urn:uuid:" + _PROJECT.encode(), b"bad", b""]),
        (b"x-briareus-agent-session-uuid", [b"00000000-0000-0000-0000-000000000001"]),
        (
            b"x-briareus-grant-revision",
            [b"0", b"-1", b"01", b"+7", b"7.0", b"9223372036854775808", b"0" * 100],
        ),
    ):
        for value in values:
            modified = [(n, v if n != name else value) for n, v in _HEADERS]
            expect_rejected(modified, {"path": "src/doc.txt"})
        expect_rejected(
            [*_HEADERS, (name, b"7")],
            {"path": "src/doc.txt"},
        )

    print("FILES_MCP_SELECTOR_CANONICALIZED_UNTRUSTED_AND_NO_NATIVE_READ_PERMIT_PASS")


if __name__ == "__main__":
    asyncio.run(main())
