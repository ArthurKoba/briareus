"""Bounded MCP protocol preflight before upstream SDK and real identity checks.

Does NOT authenticate callers or grant tools. Real resource OAuth and the
Authorization/Cedar check run in FastMCP's registered auth/middleware layer;
this outer ASGI boundary simply rejects malformed/oversized protocol bodies.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_MAX_REQUEST_BYTES = 1024 * 1024
_MAX_BODY_EVENTS = 1024
_BODY_READ_TIMEOUT_SECONDS = 8


def _unique_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject shadowed JSON-RPC fields at any nested object depth."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    """Python JSON accepts NaN/Infinity by default; MCP JSON does not."""
    raise ValueError("non-JSON numeric constant: " + value)


def _finite_json_float(value: str) -> float:
    """Reject a syntactically valid exponent that overflows to Infinity."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON numeric value")
    return number


def _header_preflight(scope: Scope) -> tuple[int | None, tuple[str, int] | None]:
    """Enforce unambiguous HTTP framing before reading a direct Hand request.

    ASGI servers usually reject invalid Content-Length/Transfer-Encoding pairs,
    but a Hand may also be reached by a private proxy or a direct test client.
    Do not rely on a particular server normalizing these security boundaries.
    """
    watched = {
        b"content-type": [],
        b"content-length": [],
        b"transfer-encoding": [],
        b"content-encoding": [],
    }
    for name, value in scope.get("headers", []):
        if not isinstance(name, bytes) or not isinstance(value, bytes):
            return None, ("MCP_HTTP_HEADERS_INVALID", 400)
        if b"\x00" in value or b"\r" in value or b"\n" in value:
            return None, ("MCP_HTTP_HEADERS_INVALID", 400)
        if name.lower() in watched:
            watched[name.lower()].append(value)

    content_types = watched[b"content-type"]
    if len(content_types) != 1:
        return None, ("MCP_CONTENT_TYPE_INVALID", 415)
    try:
        content_type = content_types[0].decode("ascii").casefold()
    except UnicodeDecodeError:
        return None, ("MCP_CONTENT_TYPE_INVALID", 415)
    media_type, separator, params = content_type.partition(";")
    if media_type.strip() != "application/json" or (
        separator and params.strip() != "charset=utf-8"
    ):
        return None, ("MCP_CONTENT_TYPE_INVALID", 415)

    lengths = watched[b"content-length"]
    if len(lengths) > 1:
        return None, ("MCP_CONTENT_LENGTH_INVALID", 400)
    declared: int | None = None
    if lengths:
        raw = lengths[0]
        if (
            not 1 <= len(raw) <= 8
            or not raw.isascii()
            or not raw.isdigit()
            or (len(raw) > 1 and raw.startswith(b"0"))
        ):
            return None, ("MCP_CONTENT_LENGTH_INVALID", 400)
        declared = int(raw)
        if declared > _MAX_REQUEST_BYTES:
            return None, ("MCP_BODY_TOO_LARGE", 413)

    transfers = watched[b"transfer-encoding"]
    if len(transfers) > 1 or (
        transfers and (transfers[0].strip().lower() != b"chunked" or lengths)
    ):
        return None, ("MCP_TRANSFER_ENCODING_INVALID", 400)

    encodings = watched[b"content-encoding"]
    if len(encodings) > 1 or (encodings and encodings[0].strip().lower() != b"identity"):
        return None, ("MCP_CONTENT_ENCODING_INVALID", 415)
    return declared, None


class EffectBoundary:
    """Preserve exact SDK lifespan/HostOrigin middleware and request bytes."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self._app(scope, receive, send)
            return
        if scope.get("raw_path") != b"/mcp" or scope.get("query_string", b"") != b"":
            # The Hand must re-enforce the canonical MCP resource URI even
            # when reached directly, independently of the public Gateway.
            await self._deny(scope, receive, send, None, "MCP_RESOURCE_PATH_INVALID", 404)
            return
        if scope.get("method") != "POST":
            # MCP DELETE may manage a transport session but never carries
            # a JSON-RPC business effect; the canonical URI still applies.
            await self._app(scope, receive, send)
            return
        declared_length, rejection = _header_preflight(scope)
        if rejection is not None:
            await self._deny(scope, receive, send, None, *rejection)
            return
        buffer = bytearray()
        try:
            # Bound total wall time, not only each receive() await: otherwise
            # a slow or empty-chunk sender can occupy an ASGI task indefinitely.
            async with asyncio.timeout(_BODY_READ_TIMEOUT_SECONDS):
                for _ in range(_MAX_BODY_EVENTS):
                    event = await receive()
                    if event.get("type") == "http.disconnect":
                        return
                    if event.get("type") != "http.request":
                        rejection = ("MCP_BODY_UNAVAILABLE", 400)
                        break
                    chunk = event.get("body", b"")
                    if (
                        not isinstance(chunk, bytes)
                        or len(buffer) + len(chunk) > _MAX_REQUEST_BYTES
                    ):
                        rejection = ("MCP_BODY_TOO_LARGE", 413)
                        break
                    buffer.extend(chunk)
                    if not event.get("more_body", False):
                        break
                else:
                    rejection = ("MCP_BODY_TOO_FRAGMENTED", 413)
        except TimeoutError:
            rejection = ("MCP_BODY_READ_TIMEOUT", 408)
        if rejection is None and declared_length is not None and len(buffer) != declared_length:
            rejection = ("MCP_CONTENT_LENGTH_INVALID", 400)
        # Send the rejection OUTSIDE the read timeout; a slow ASGI send
        # must not trigger a second response after the first one started.
        if rejection is not None:
            await self._deny(scope, receive, send, None, *rejection)
            return
        try:
            # JSON-RPC over HTTP is UTF-8; accepting auto-detected UTF-16
            # here could disagree with FastMCP's downstream UTF-8 decoder.
            data: Any = json.loads(
                buffer.decode("utf-8"),
                object_pairs_hook=_unique_json_fields,
                parse_constant=_reject_non_json_constant,
                parse_float=_finite_json_float,
            )
        except (ValueError, UnicodeDecodeError, RecursionError):
            await self._deny(scope, receive, send, None, "MCP_INVALID_JSON", 400)
            return
        if not isinstance(data, dict):
            await self._deny(scope, receive, send, None, "MCP_BATCH_NOT_SUPPORTED", 400)
            return
        try:
            # RFC 8259 JSON consists of Unicode scalar values. Escaped,
            # unpaired UTF-16 surrogate code units would produce malformed
            # strings for SDK handlers despite valid UTF-8 transport bytes.
            json.dumps(data, ensure_ascii=False).encode("utf-8")
        except (ValueError, UnicodeEncodeError, RecursionError):
            await self._deny(scope, receive, send, None, "MCP_INVALID_JSON", 400)
            return
        sent = False

        async def replay() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(buffer), "more_body": False}
            return await receive()

        await self._app(scope, replay, send)

    @staticmethod
    async def _deny(
        scope: Scope, receive: Receive, send: Send, request_id: object, code: str, status: int
    ) -> None:
        response = JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id if isinstance(request_id, (str, int)) else None,
                "error": {"code": -32001, "message": code},
            },
            status_code=status,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
        await response(scope, receive, send)
