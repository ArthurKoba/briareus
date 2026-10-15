"""Direct Hand MCP framing proof; no bearer, owner grant or privileged tool."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from hand_runtime._effect_boundary import EffectBoundary
from starlette.types import Receive, Scope, Send

_BODY = b'{"jsonrpc":"2.0","method":"initialize","id":1}'


async def _exercise(
    extra_headers: list[tuple[bytes, bytes]],
    *,
    body: bytes = _BODY,
    chunks: tuple[bytes, ...] | None = None,
    raw_path: bytes = b"/mcp",
    query: bytes = b"",
    method: str = "POST",
) -> tuple[int, str | None, int, bytes, int]:
    received = 0
    downstream: list[bytes] = []
    outbound: list[dict[str, Any]] = []
    pieces = chunks or (body,)
    iterator = iter(pieces)

    async def receive() -> dict[str, Any]:
        nonlocal received
        received += 1
        try:
            part = next(iterator)
        except StopIteration as exc:
            raise AssertionError("ASGI app consumed beyond declared body") from exc
        return {
            "type": "http.request",
            "body": part,
            "more_body": received < len(pieces),
        }

    async def send(message: dict[str, Any]) -> None:
        outbound.append(message)

    async def inner(_scope: Scope, replay: Receive, sender: Send) -> None:
        event = await replay()
        assert event["type"] == "http.request" and not event["more_body"]
        downstream.append(event["body"])
        await sender({"type": "http.response.start", "status": 202, "headers": []})
        await sender({"type": "http.response.body", "body": b"", "more_body": False})

    app = EffectBoundary(inner)
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "path": "/mcp",
            "raw_path": raw_path,
            "query_string": query,
            "scheme": "http",
            "headers": [(b"host", b"briareus-files:8000"), *extra_headers],
        },
        receive,
        send,
    )
    start = next(x for x in outbound if x["type"] == "http.response.start")
    data = b"".join(x.get("body", b"") for x in outbound if x["type"] == "http.response.body")
    error = json.loads(data)["error"]["message"] if data else None
    return start["status"], error, len(downstream), downstream[0] if downstream else b"", received


async def main() -> None:
    good = [(b"content-type", b"application/json"), (b"content-length", str(len(_BODY)).encode())]
    for headers in (
        good,
        [(b"content-type", b"Application/JSON; charset=UTF-8"), good[1]],
        [(b"content-type", b"application/json"), (b"transfer-encoding", b"chunked")],
    ):
        status, error, calls, payload, read_events = await _exercise(headers)
        assert (status, error, calls, payload, read_events) == (202, None, 1, _BODY, 1)
    status, error, calls, payload, read_events = await _exercise(
        good, chunks=(_BODY[:10], b"", _BODY[10:])
    )
    assert (status, error, calls, payload, read_events) == (202, None, 1, _BODY, 3)

    for raw_path, query in ((b"/%6dcp", b""), (b"/mcp", b"forged=actor")):
        status, error, calls, payload, events = await _exercise(
            good, raw_path=raw_path, query=query
        )
        assert (status, error, calls, payload, events) == (
            404,
            "MCP_RESOURCE_PATH_INVALID",
            0,
            b"",
            0,
        )

    status, error, calls, payload, events = await _exercise(
        good, raw_path=b"/%6dcp", method="DELETE"
    )
    assert (status, error, calls, payload, events) == (404, "MCP_RESOURCE_PATH_INVALID", 0, b"", 0)

    for headers, expected, expected_read in (
        ([(b"content-length", str(len(_BODY)).encode())], "MCP_CONTENT_TYPE_INVALID", 0),
        ([*good, (b"content-type", b"application/json")], "MCP_CONTENT_TYPE_INVALID", 0),
        ([(b"content-type", b"application/xml")], "MCP_CONTENT_TYPE_INVALID", 0),
        ([(b"content-type", b"application/json\r\n")], "MCP_HTTP_HEADERS_INVALID", 0),
        ([(b"content-type", b"application/json; charset=latin1")], "MCP_CONTENT_TYPE_INVALID", 0),
        ([*good, (b"content-length", b"44")], "MCP_CONTENT_LENGTH_INVALID", 0),
        (
            [(b"content-type", b"application/json"), (b"content-length", b"0" + good[1][1])],
            "MCP_CONTENT_LENGTH_INVALID",
            0,
        ),
        (
            [(b"content-type", b"application/json"), (b"content-length", b"abc")],
            "MCP_CONTENT_LENGTH_INVALID",
            0,
        ),
        (
            [(b"content-type", b"application/json"), (b"content-length", b"1048577")],
            "MCP_BODY_TOO_LARGE",
            0,
        ),
        ([*good, (b"transfer-encoding", b"chunked")], "MCP_TRANSFER_ENCODING_INVALID", 0),
        (
            [(b"content-type", b"application/json"), (b"transfer-encoding", b"gzip")],
            "MCP_TRANSFER_ENCODING_INVALID",
            0,
        ),
        ([*good, (b"content-encoding", b"gzip")], "MCP_CONTENT_ENCODING_INVALID", 0),
        (
            [*good, (b"content-encoding", b"identity"), (b"content-encoding", b"identity")],
            "MCP_CONTENT_ENCODING_INVALID",
            0,
        ),
        (
            [(b"content-type", b"application/json"), (b"content-length", b"1")],
            "MCP_CONTENT_LENGTH_INVALID",
            1,
        ),
    ):
        status, error, calls, payload, read_events = await _exercise(headers)
        assert status in (400, 413, 415), (headers, status)
        assert (error, calls, payload, read_events) == (expected, 0, b"", expected_read), (
            headers,
            error,
            calls,
            read_events,
        )

    print("DIRECT_HAND_HTTP_FRAMING_ACCEPTS_CANONICAL_MCP_AND_REJECTS_AMBIGUITY")


if __name__ == "__main__":
    asyncio.run(main())
