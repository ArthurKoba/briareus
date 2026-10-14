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
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ._mcp_admission import (
    McpAdmissionRejected,
    admission_error,
    authorize_connection,
    parse_connection_admission,
)
from .route_telemetry import RouteTelemetry
from .single_origin import MCP_ENDPOINTS, PUBLIC_HOST, SingleOriginGuard, unavailable_routes

_PANEL_UPSTREAM = "http://briareus-admin-ui:8080"
_API_UPSTREAM = "http://briareus-admin-api:8000"
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


def _api_headers(request: Request) -> list[tuple[bytes, bytes]]:
    """Preserve end-to-end credentials/headers; discard caller proxy claims."""
    connection_tokens: set[str] = set()
    for k, v in request.scope.get("headers", []):
        if k.lower() == b"connection":
            connection_tokens.update(
                part.strip().casefold() for part in v.decode("latin1").split(",")
            )
    return [
        (key, value)
        for key, value in request.scope.get("headers", [])
        if key.decode("ascii").casefold() not in _HOP_HEADERS
        and key.decode("ascii").casefold() not in _PROXY_ASSERTIONS
        and key.decode("ascii").casefold() not in connection_tokens
    ]


class ThinGateway:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._slots = asyncio.Semaphore(64)
        self._draining = False
        self._open: set[httpx.Response] = set()

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
                for response in tuple(self._open):
                    await response.aclose()
                self._open.clear()
                self._client = None

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
                response = await client.send(
                    client.build_request(
                        request.method,
                        _PANEL_UPSTREAM + quote(path, safe="/-._~"),
                        headers={"accept": "*/*", "accept-encoding": "identity"},
                    ),
                    stream=True,
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
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            return admission_error("MCP_CONTENT_TYPE_INVALID", 415)
        client = self._client
        if client is None or self._draining:
            return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
        except TimeoutError:
            return admission_error("MCP_GATEWAY_BUSY", 503)
        try:
            blocked = await authorize_connection(client, admission)
            if blocked is not None:
                self._slots.release()
                return blocked
            payload = bytearray()
            async for chunk in request.stream():
                payload.extend(chunk)
                if len(payload) > 1024 * 1024:
                    self._slots.release()
                    return admission_error("MCP_BODY_TOO_LARGE", 413)
            headers = {
                "Authorization": admission.bearer,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            protocol = request.headers.getlist("mcp-protocol-version")
            if len(protocol) == 1 and 0 < len(protocol[0]) <= 64:
                headers["Mcp-Protocol-Version"] = protocol[0]
            upstream_request = client.build_request(
                "POST", admission.target, headers=headers, content=bytes(payload)
            )
            upstream = await client.send(upstream_request, stream=True)
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
            await upstream.aclose()
            self._slots.release()
            return admission_error("MCP_UPSTREAM_UNAVAILABLE", 503)
        self._open.add(upstream)

        async def stream() -> AsyncIterator[bytes]:
            try:
                async for data in upstream.aiter_raw():
                    yield data
            finally:
                self._open.discard(upstream)
                await upstream.aclose()
                self._slots.release()

        streamed = StreamingResponse(stream(), status_code=upstream.status_code)
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
        query = request.scope.get("query_string", b"")
        if not isinstance(query, bytes):
            return Response(status_code=400)
        # Construct only a fixed private destination; the public Host is never a URL target.
        try:
            raw_url = path + ("?" + query.decode("ascii") if query else "")
            upstream = _RAUTHY_UPSTREAM if rauthy else _API_UPSTREAM
            target_url = httpx.URL(upstream + raw_url)
            if (target_url.host, target_url.port) != (
                ("briareus-rauthy", 8080) if rauthy else ("briareus-admin-api", 8000)
            ):
                return Response(status_code=400)
        except (UnicodeDecodeError, ValueError, httpx.InvalidURL):
            return Response(status_code=400)
        client = self._client
        if client is None or self._draining:
            return self._unavailable()
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
        except TimeoutError:
            return self._unavailable()
        try:
            headers = _api_headers(request)
            if rauthy:
                # Derive proxy claims from our fixed public origin, never the caller.
                headers.extend(
                    (
                        (b"host", PUBLIC_HOST.encode("ascii")),
                        (b"x-forwarded-host", PUBLIC_HOST.encode("ascii")),
                        (b"x-forwarded-proto", b"https"),
                    )
                )
            upstream_request = client.build_request(
                request.method,
                target_url,
                headers=headers,
                content=request.stream(),
            )
            upstream = await client.send(upstream_request, stream=True)
        except asyncio.CancelledError:
            self._slots.release()
            raise
        except (httpx.HTTPError, ValueError, UnicodeError):
            self._slots.release()
            return self._unavailable()
        except BaseException:
            self._slots.release()
            raise
        self._open.add(upstream)

        async def body() -> AsyncIterator[bytes]:
            try:
                async for data in upstream.aiter_raw():
                    yield data
            finally:
                self._open.discard(upstream)
                await upstream.aclose()
                self._slots.release()

        streamed = StreamingResponse(body(), status_code=upstream.status_code)
        # Preserve duplicate Set-Cookie and other end-to-end response headers.
        # ASGI streaming manages framing; do not send hop-by-hop headers.
        streamed.raw_headers = [
            (key, value)
            for key, value in upstream.headers.raw
            if key.decode("ascii").casefold() not in _HOP_HEADERS
        ]
        return streamed


def build_app() -> Starlette:
    transport = ThinGateway()
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
