"""Public static Panel and transparent /api reverse proxy.

Authentication, sessions, identity and all API routing belong to Admin API.
No Gateway C2 adapter, JWT verifier or special Identity destination exists.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .single_origin import SingleOriginGuard, unavailable_routes

_PANEL_UPSTREAM = "http://briareus-admin-ui:8080"
_API_UPSTREAM = "http://briareus-admin-api:8000"
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
        """Forward the original /api path and method. Admin API owns all auth."""
        path = _raw_path(request)
        if path is None or (path != "/api" and not path.startswith("/api/")):
            return Response(status_code=404)
        query = request.scope.get("query_string", b"")
        if not isinstance(query, bytes):
            return Response(status_code=400)
        # Construct only a fixed private destination; the public Host is never a URL target.
        try:
            raw_url = path + ("?" + query.decode("ascii") if query else "")
            target_url = httpx.URL(_API_UPSTREAM + raw_url)
            if target_url.host != "briareus-admin-api" or target_url.port != 8000:
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
            upstream_request = client.build_request(
                request.method,
                target_url,
                headers=_api_headers(request),
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
    return Starlette(
        routes=[
            Route("/", transport.static, methods=_METHODS),
            Route("/robots.txt", transport.static, methods=_METHODS),
            Route("/sitemap.xml", transport.static, methods=_METHODS),
            Route("/panel", transport.static, methods=_METHODS),
            Route("/panel/{path:path}", transport.static, methods=_METHODS),
            Route("/api", transport.api, methods=_METHODS),
            Route("/api/{path:path}", transport.api, methods=_METHODS),
            *unavailable_routes(),
        ],
        middleware=[Middleware(SingleOriginGuard)],
        lifespan=transport.lifespan,
    )
