"""Single-origin Panel, API, and upstream Rauthy OIDC reverse proxy.

Gateway only forwards fixed public namespaces; identity, JWT verification,
business permissions and authentication remain upstream responsibilities.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ._api_contract import public_api_path, retired_auth_path
from ._mcp_admission import (
    McpAdmissionRejected,
    TrustedGatewayDecisionPort,
    admission_error,
    authorize_connection,
    parse_connection_admission,
)
from ._mcp_body import McpBodyRejected, read_mcp_body
from ._proxy_start import PendingProxyStart
from ._proxy_stream import ProxyStreamingResponse
from ._rauthy_admin_privacy import classify_rauthy_public_path
from .route_telemetry import RouteTelemetry
from .single_origin import MCP_ENDPOINTS, PUBLIC_HOST, SingleOriginGuard, unavailable_routes

_PANEL_UPSTREAM = "http://briareus-control-panel-ui:8080"
_API_UPSTREAM = "http://briareus-control-panel-api:8000"
_RAUTHY_UPSTREAM = "http://briareus-rauthy:8080"
_PUBLIC_FILES = frozenset({"/", "/robots.txt", "/sitemap.xml", "/panel/"})
_PANEL_ASSET = re.compile(
    r"^/panel/assets/[A-Za-z0-9][A-Za-z0-9._-]{0,160}\.(?:js|css|svg|png|webp|ico|woff2)$"
)
_STATIC_TYPE = {
    "/": frozenset({"text/html"}),
    "/panel/": frozenset({"text/html"}),
    "/robots.txt": frozenset({"text/plain"}),
    "/sitemap.xml": frozenset({"application/xml", "text/xml"}),
}
_ASSET_TYPES = {
    "js": frozenset({"text/javascript", "application/javascript"}),
    "css": frozenset({"text/css"}),
    "svg": frozenset({"image/svg+xml"}),
    "png": frozenset({"image/png"}),
    "webp": frozenset({"image/webp"}),
    "ico": frozenset({"image/x-icon", "image/vnd.microsoft.icon"}),
    "woff2": frozenset({"font/woff2", "application/font-woff"}),
}
_HOP_HEADERS = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
)
_PROXY_ASSERTIONS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-real-ip",
        "x-original-url",
        "x-rewrite-url",
    }
)
_TIMEOUT = httpx.Timeout(connect=3, read=60, write=30, pool=3)
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@dataclass(frozen=True, slots=True)
class RouteSpec:
    """Public route template and its fixed internal service destination."""

    template: str
    target: Literal["panel-ui", "panel-api", "rauthy"]


# Runtime routing policy contains no principal, permissions or Identity paths.
_ROUTE_TABLE: tuple[RouteSpec, ...] = (
    RouteSpec("/", "panel-ui"),
    RouteSpec("/robots.txt", "panel-ui"),
    RouteSpec("/sitemap.xml", "panel-ui"),
    RouteSpec("/panel", "panel-ui"),
    RouteSpec("/panel/{path:path}", "panel-ui"),
    RouteSpec("/api", "panel-api"),
    RouteSpec("/api/{path:path}", "panel-api"),
    RouteSpec("/auth/v1", "rauthy"),
    RouteSpec("/auth/v1/{path:path}", "rauthy"),
)


def _media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().casefold()


def _raw_path(request: Request) -> str | None:
    raw = request.scope.get("raw_path", b"")
    if not isinstance(raw, bytes):
        return None
    try:
        path = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not path.startswith("/") or any(c in path for c in ("#", "\\", "\r", "\n", "\x00")):
        return None
    return path


def _connection_tokens(headers: list[tuple[bytes, bytes]]) -> set[str]:
    return {
        token.strip().casefold()
        for name, value in headers
        if name.lower() == b"connection"
        for token in value.decode("latin1").split(",")
    }


def _api_headers(request: Request) -> list[tuple[bytes, bytes]]:
    """Forward end-to-end headers, never browser-originated proxy identity."""
    incoming = request.scope.get("headers", [])
    connection_tokens = _connection_tokens(incoming)
    result: list[tuple[bytes, bytes]] = []
    for name, value in incoming:
        key = name.decode("ascii").casefold()
        if (
            key in _HOP_HEADERS
            or key in _PROXY_ASSERTIONS
            or key.startswith("x-forwarded-")
            or key in connection_tokens
        ):
            continue
        result.append((name, value))
    return result


def _api_declared_length(request: Request, *, rauthy: bool) -> bytes | None:
    """Preserve a single bounded original BFF length, never ambiguous framing."""
    if rauthy:
        # Rauthy provider routes retain their existing streaming semantics.
        return None
    lengths = request.headers.getlist("content-length")
    if not lengths:
        return None
    value = lengths[0]
    if (
        len(lengths) != 1
        or not value.isascii()
        or not value.isdecimal()
        or len(value) > 19
        or int(value) > 2**63 - 1
        or request.headers.getlist("transfer-encoding")
    ):
        raise ValueError("ambiguous Control Panel API HTTP framing")
    return value.encode("ascii")


def _upstream_headers(
    request: Request, *, rauthy: bool, declared_length: bytes | None
) -> list[tuple[bytes, bytes]]:
    """Separate outbound origin claims from incoming browser request headers."""
    headers = _api_headers(request)
    if declared_length is not None:
        headers.append((b"content-length", declared_length))
    # After SingleOriginGuard has independently checked exactly one
    # accepted public Host, give the PRIVATE API owner exactly one stable
    # canonical authority. HTTPX otherwise synthesizes the container DNS
    # destination Host, which the Backend native credentials BFF correctly
    # rejects. Never forward client Host / :443 / X-Forwarded assertions.
    headers.append((b"host", PUBLIC_HOST.encode("ascii")))
    if rauthy:
        # Rauthy owner also requires trusted Gateway external-origin hints.
        headers.extend(
            (
                (b"x-forwarded-host", PUBLIC_HOST.encode("ascii")),
                (b"x-forwarded-proto", b"https"),
            )
        )
    return headers


class ThinGateway:
    def __init__(self, private_decision: TrustedGatewayDecisionPort | None = None) -> None:
        self._private_decision = private_decision
        self._client: httpx.AsyncClient | None = None
        self._slots = asyncio.Semaphore(64)
        self._draining = False
        self._open: set[httpx.Response] = set()
        self._streams: set[ProxyStreamingResponse] = set()
        self._pending: set[PendingProxyStart] = set()

    @asynccontextmanager
    async def lifespan(self, _app: Starlette) -> AsyncIterator[None]:
        self._draining = False
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=24),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            self._client = client
            try:
                yield
            finally:
                self._draining = True
                self._client = None
                await self._drain_streams()

    async def _drain_streams(self) -> None:
        async def close_all() -> None:
            # Include requests still waiting for a client body or first
            # owner response; they have not become tracked streams yet.
            await asyncio.gather(
                *(pending.abort() for pending in tuple(self._pending)),
                return_exceptions=True,
            )
            # Each stream owns a three-second close deadline and frees its
            # own pool slot once. Parallel close avoids 64 sequential waits.
            await asyncio.gather(
                *(stream.aclose() for stream in tuple(self._streams)),
                return_exceptions=True,
            )

        cleanup = asyncio.create_task(close_all())
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _send_upstream(
        self, client: httpx.AsyncClient, request: httpx.Request
    ) -> httpx.Response:
        if self._draining:
            raise httpx.ReadError("gateway is draining")
        pending = PendingProxyStart(client, request)
        self._pending.add(pending)
        try:
            return await pending.take_response()
        finally:
            self._pending.discard(pending)

    def _stream_response(self, upstream: httpx.Response) -> ProxyStreamingResponse:
        self._open.add(upstream)
        response = ProxyStreamingResponse(
            upstream, slots=self._slots, open_responses=self._open, tracked_streams=self._streams
        )
        self._streams.add(response)
        return response

    @staticmethod
    def _unavailable() -> Response:
        return JSONResponse(
            {"code": "GATEWAY_UPSTREAM_UNAVAILABLE"},
            status_code=502,
            headers={"Cache-Control": "no-store"},
        )

    async def static(self, request: Request) -> Response:
        path = _raw_path(request)
        if request.method not in {"GET", "HEAD"} or request.scope.get("query_string", b""):
            return Response(status_code=404)
        if path == "/panel":
            return Response(
                status_code=308, headers={"Location": "/panel/", "Cache-Control": "no-store"}
            )
        if path is None or (path not in _PUBLIC_FILES and not _PANEL_ASSET.fullmatch(path)):
            return Response(status_code=404)
        client = self._client
        if client is None or self._draining:
            return self._unavailable()
        is_asset = bool(_PANEL_ASSET.fullmatch(path))
        max_bytes = 2 * 1024 * 1024 if is_asset else 256 * 1024
        expected = _ASSET_TYPES[path.rsplit(".", 1)[-1]] if is_asset else _STATIC_TYPE[path]
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
        except TimeoutError:
            return self._unavailable()
        try:
            async with asyncio.timeout(8):
                response = await self._send_upstream(
                    client,
                    client.build_request(
                        request.method,
                        _PANEL_UPSTREAM + quote(path, safe="/-._~"),
                        headers={"accept": "*/*", "accept-encoding": "identity"},
                    ),
                )
                try:
                    if (
                        response.status_code != 200
                        or _media_type(response.headers.get("content-type", "")) not in expected
                    ):
                        return self._unavailable()
                    if response.headers.get("content-encoding", "identity").lower() not in {
                        "",
                        "identity",
                    }:
                        return self._unavailable()
                    length = response.headers.get("content-length")
                    if length is not None and not 0 <= int(length) <= max_bytes:
                        return self._unavailable()
                    parts: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_raw():
                        total += len(chunk)
                        if total > max_bytes:
                            return self._unavailable()
                        parts.append(chunk)
                finally:
                    await response.aclose()
            payload = b"".join(parts)
            if path == "/panel/" and request.method == "GET" and b"noindex" not in payload.lower():
                return self._unavailable()
            return Response(
                content=b"" if request.method == "HEAD" else payload,
                status_code=200,
                headers={
                    "Content-Type": response.headers["content-type"],
                    "Cache-Control": "no-store" if path == "/panel/" else "public, max-age=60",
                    "X-Content-Type-Options": "nosniff",
                    **({"X-Robots-Tag": "noindex, nofollow"} if path == "/panel/" else {}),
                },
            )
        except asyncio.CancelledError:
            raise
        except (ValueError, httpx.HTTPError, TimeoutError):
            return self._unavailable()
        finally:
            self._slots.release()

    async def api(self, request: Request) -> Response:
        """Preserve the Admin API's unmodified public /api/* contract."""
        return await self._proxy(request, rauthy=False)

    async def oidc(self, request: Request) -> Response:
        """Forward only the real upstream Rauthy /auth/v1/* namespace."""
        return await self._proxy(request, rauthy=True)

    async def mcp(self, request: Request) -> Response:
        """Coarse `mcp.connect` admission; Hand independently checks each effect."""
        try:
            admission = parse_connection_admission(request)
        except McpAdmissionRejected as exc:
            return admission_error(exc.code, exc.status_code)
        content_types = request.headers.getlist("content-type")
        if len(content_types) != 1:
            return admission_error("MCP_CONTENT_TYPE_INVALID", 415)
        media_type, separator, parameter = content_types[0].partition(";")
        if media_type.strip().lower() != "application/json" or (
            separator and parameter.strip().lower() != "charset=utf-8"
        ):
            return admission_error("MCP_CONTENT_TYPE_INVALID", 415)
        client = self._client
        if client is None or self._draining or self._private_decision is None:
            # No authenticated private peer: reject before reading an
            # attacker-controlled request body or forwarding any Bearer.
            return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
        except TimeoutError:
            return admission_error("MCP_GATEWAY_BUSY", 503)
        try:
            # Reject malformed, ambiguous, oversized or slow JSON before the
            # expensive private Authorization peer is contacted. Valid body
            # bytes are still forwarded unchanged to the Hand's own guard.
            try:
                payload = await read_mcp_body(request)
            except McpBodyRejected as exc:
                self._slots.release()
                return admission_error(exc.code, exc.status_code)
            blocked = await authorize_connection(self._private_decision, admission)
            if blocked is not None:
                self._slots.release()
                return blocked
            headers = {
                "Authorization": admission.bearer,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                # Forward bounded, canonical *selectors*, never unverified actor
                # identity or caller-supplied peer evidence. Every Hand repeats
                # signed identity + current Authorization/Cedar admission.
                "X-Briareus-Project-UUID": str(admission.project_uuid),
                "X-Briareus-Agent-Session-UUID": str(admission.agent_session_uuid),
                "X-Briareus-Grant-Revision": str(admission.grant_revision),
            }
            protocol = request.headers.getlist("mcp-protocol-version")
            if len(protocol) == 1 and 0 < len(protocol[0]) <= 64:
                headers["Mcp-Protocol-Version"] = protocol[0]
            upstream_request = client.build_request(
                "POST", admission.target, headers=headers, content=payload
            )
            upstream = await self._send_upstream(client, upstream_request)
        except asyncio.CancelledError:
            self._slots.release()
            raise
        except (httpx.HTTPError, ValueError, TimeoutError):
            self._slots.release()
            return admission_error("MCP_UPSTREAM_UNAVAILABLE", 503)
        except BaseException:
            self._slots.release()
            raise
        # HTTP MCP also uses 202 for accepted notifications, and Hands may
        # independently deny a protected effect despite coarse admission.
        if upstream.status_code not in {200, 202, 204, 400, 401, 403, 404, 409, 422, 429, 503}:
            # Even a rejected upstream response needs the same bounded,
            # exactly-once cleanup; a close error must not strand admission.
            rejected_stream = self._stream_response(upstream)
            await rejected_stream.aclose()
            return admission_error("MCP_UPSTREAM_UNAVAILABLE", 503)
        streamed = self._stream_response(upstream)
        if self._draining:
            await streamed.aclose()
            return admission_error("MCP_UPSTREAM_UNAVAILABLE", 503)
        # Only protocol framing metadata may cross the private Hand boundary.
        # Never forward a provider Set-Cookie, Location or internal server hint.
        streamed.raw_headers = [
            (key, value)
            for key, value in upstream.headers.raw
            if key.decode("ascii").casefold()
            in {"content-type", "mcp-session-id", "mcp-protocol-version"}
        ] + [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
        return streamed

    async def _proxy(self, request: Request, *, rauthy: bool) -> Response:
        path = _raw_path(request)
        prefix = "/auth/v1" if rauthy else "/api"
        if path is None or (path != prefix and not path.startswith(prefix + "/")):
            return Response(status_code=404)
        if not rauthy:
            decoded = request.scope.get("path")
            if retired_auth_path(raw_path=path, decoded_path=decoded, method=request.method):
                return JSONResponse(
                    {"code": "AUTH_API_ROUTE_RETIRED"},
                    status_code=404,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                )
            if not public_api_path(raw_path=path, decoded_path=decoded, method=request.method):
                # No implicit /api/* access to future private API routes.
                # The public contract is /api/v1/* plus the registered
                # exact GET OAuth callback; neither is a trusted Permit.
                return JSONResponse(
                    {"code": "API_ROUTE_NOT_PUBLIC"},
                    status_code=404,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                )
        if rauthy:
            # Rauthy 0.37.1 interleaves Admin APIs and essential login/
            # recovery/self-service handlers; use source-verified route and
            # method boundaries rather than a blanket /auth/v1 deny.
            route_disposition = classify_rauthy_public_path(path, request.method)
            if route_disposition == "bad_path":
                return Response(status_code=400)
            if route_disposition == "private_admin":
                return JSONResponse(
                    {"code": "RAUTHY_ADMIN_ROUTE_PRIVATE"},
                    status_code=404,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                )
        query = request.scope.get("query_string", b"")
        if not isinstance(query, bytes):
            return Response(status_code=400)
        # Construct only a fixed private destination; the public Host is never a URL target.
        try:
            raw_url = path + ("?" + query.decode("ascii") if query else "")
            upstream = _RAUTHY_UPSTREAM if rauthy else _API_UPSTREAM
            target_url = httpx.URL(upstream + raw_url)
            if (target_url.host, target_url.port) != (
                ("briareus-rauthy", 8080) if rauthy else ("briareus-control-panel-api", 8000)
            ):
                return Response(status_code=400)
        except (UnicodeDecodeError, ValueError, httpx.InvalidURL):
            return Response(status_code=400)
        # The native Backend expects exact Content-Length: 2 for "{}"
        # Init/PoW, but Rauthy must keep its established stream behavior.
        try:
            declared_length = _api_declared_length(request, rauthy=rauthy)
        except ValueError:
            return Response(status_code=400)
        client = self._client
        if client is None or self._draining:
            return self._unavailable()
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
        except TimeoutError:
            return self._unavailable()
        try:
            headers = _upstream_headers(request, rauthy=rauthy, declared_length=declared_length)
            upstream_request = client.build_request(
                request.method,
                target_url,
                headers=headers,
                content=request.stream(),
            )
            upstream = await self._send_upstream(client, upstream_request)
        except asyncio.CancelledError:
            self._slots.release()
            raise
        except (httpx.HTTPError, ValueError, UnicodeError):
            self._slots.release()
            return self._unavailable()
        except BaseException:
            self._slots.release()
            raise
        streamed = self._stream_response(upstream)
        if self._draining:
            await streamed.aclose()
            return self._unavailable()
        # Preserve duplicate Set-Cookie and other end-to-end response headers.
        # ASGI streaming manages framing; do not send hop-by-hop headers.
        excluded = _HOP_HEADERS | _connection_tokens(upstream.headers.raw)
        streamed.raw_headers = [
            (key, value)
            for key, value in upstream.headers.raw
            if key.decode("ascii").casefold() not in excluded
        ]
        return streamed


def build_app(*, private_decision: TrustedGatewayDecisionPort | None = None) -> Starlette:
    transport = ThinGateway(private_decision)
    handlers = {
        "panel-ui": transport.static,
        "panel-api": transport.api,
        "rauthy": transport.oidc,
    }
    return Starlette(
        routes=[
            *[
                Route(spec.template, handlers[spec.target], methods=_METHODS)
                for spec in _ROUTE_TABLE
            ],
            *[Route(path, transport.mcp, methods=["POST"]) for path in MCP_ENDPOINTS.values()],
            *unavailable_routes(),
        ],
        middleware=[Middleware(SingleOriginGuard), Middleware(RouteTelemetry)],
        lifespan=transport.lifespan,
    )
