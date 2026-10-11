"""Private, bounded one-origin HTTP/SSE and WS transport composition.

Source-only. The published application supplies NO trusted authenticated port,
so NONE of these upstream transports is activated. Backend A18 owns verified
User/Service/C2/current owner grant and short-lived recipient-bound assertions;
D6 owns actual proxy TLS, Docker networking, uv locks and exit-78 removal.
This source never infers trust from a Host, cookie, bearer or X-Forwarded-*.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .single_origin import MCP_ENDPOINTS, PUBLIC_ORIGIN

GatewayTarget = Literal[
    "panel", "api", "files", "terminal", "web", "svc", "infrastructure", "reverse"
]

# Derived from accepted, published deploy/<module>/docker-compose.yaml
# briareus-net alias + EXPOSE, not an HTTP client-supplied URL.
PRIVATE_UPSTREAMS: Mapping[GatewayTarget, tuple[str, int]] = {
    "panel": ("briareus-admin-ui", 8080),
    "api": ("briareus-admin-api", 8000),
    "files": ("briareus-files", 8000),
    "terminal": ("briareus-terminal", 8000),
    "web": ("briareus-web", 8000),
    "svc": ("briareus-svc", 8000),
    "infrastructure": ("briareus-infrastructure", 8000),
    "reverse": ("briareus-reverse", 8000),
}

# Deliberately no Authorization, owner SQL or OAuth issuer target: A18 must
# separately accept the correct resource metadata and current issuer first.
_ALLOWED_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_SAFE_FORWARD = frozenset(
    {
        "accept",
        "content-type",
        "mcp-protocol-version",
        "mcp-session-id",
        "last-event-id",
        "authorization",
        "cookie",
        "x-csrf-token",
        "idempotency-key",
        "operation-uuid",
        "x-request-id",
    }
)
_RESPONSE_DENY = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "set-cookie",
        "location",
        "access-control-allow-origin",
    }
)
_STRICT_QUERY = re.compile(rb"^[\x20-\x7e]*$")
_MAX_REQUEST_BYTES = 1024 * 1024
_MAX_WS_MESSAGE_BYTES = 1024 * 1024
_MAX_PUBLIC_STATIC_BYTES = 256 * 1024
_PUBLIC_STATIC_PATHS = frozenset({"/", "/robots.txt", "/sitemap.xml"})
_HTTP_TIMEOUT = httpx.Timeout(connect=3.0, read=60.0, write=15.0, pool=3.0)


class GatewayTransportDenied(RuntimeError):
    """Typed private refusal; never serialize its message from a remote peer."""


@dataclass(frozen=True, slots=True)
class GatewayRoute:
    target: GatewayTarget
    upstream_path: str
    public_path: str
    original_mcp: bool = False
    public_static: bool = False


def route_for_path(path: str) -> GatewayRoute | None:
    """Exact allowlist, no generic /hands/{module}/mcp catch-all."""
    if not path.startswith("/") or "\\" in path or "//" in path or "\x00" in path:
        return None
    segments = path.split("/")
    if any(seg in {".", ".."} or "%" in seg for seg in segments):
        return None
    if path in _PUBLIC_STATIC_PATHS:
        return GatewayRoute("panel", path, path, public_static=True)
    if path in {"/panel", "/panel/"} or path.startswith("/panel/"):
        # Panel's Nginx owns /panel -> /panel/ (308) and SPA /panel/*.
        # Never strip to /: that is the distinct public project landing.
        return GatewayRoute("panel", path, path)
    if path in {"/api", "/api/"}:
        return GatewayRoute("api", "/", path)
    if path.startswith("/api/"):
        # Private Admin API source must independently verify this namespace.
        return GatewayRoute("api", "/" + path[len("/api/") :], path)
    for module, public in MCP_ENDPOINTS.items():
        if path == public:
            return GatewayRoute(module, "/mcp", path, original_mcp=True)  # type: ignore[arg-type]
    return None


@dataclass(frozen=True, slots=True)
class VerifiedGatewayForwarding:
    """Produced ONLY by trusted A18/C2 port, never from request headers.

    Must be signed, single-recipient and current-grant verified by the provider;
    this container does not invent a signer, session or accepted OAuth token.
    """

    target: GatewayTarget
    method: str
    operation_uuid: UUID | None
    recipient_service_id: UUID
    recipient_instance_uuid: UUID
    expires_at: datetime
    headers: tuple[tuple[str, str], ...]


class TrustedGatewaySourcePort(Protocol):
    async def require_current(
        self, request: Request | WebSocket, *, target: GatewayTarget, method: str
    ) -> VerifiedGatewayForwarding: ...

    async def revalidate_current(
        self,
        request: Request | WebSocket,
        *,
        previous: VerifiedGatewayForwarding,
        body_sha256: str | None,
    ) -> VerifiedGatewayForwarding:
        """Read-only fresh current owner/grant/recipient/expiry evaluation.

        MUST NOT consume the original one-use JTI a second time or mint a
        second delegation/operation UUID. Verify previous signed evidence,
        matching original actor/Project/AgentSession and body fingerprint
        against authoritative current Identity/Control/Access source.
        An unavailable owner or a stale/revoked original fails closed.
        """
        ...


class PrivateWebSocketChannel(Protocol):
    async def send_text(self, payload: str) -> None: ...
    async def send_bytes(self, payload: bytes) -> None: ...
    async def receive(self) -> str | bytes: ...
    async def close(self, code: int = 1000) -> None: ...


class TrustedWebSocketDialer(Protocol):
    """D6/A18 accepted private peer socket, not a browser-provided ws URL."""

    def connect(
        self, route: GatewayRoute, headers: Mapping[str, str], query: bytes
    ) -> AbstractAsyncContextManager[PrivateWebSocketChannel]: ...


def require_forwarding(
    evidence: object, *, target: GatewayTarget, method: str, original: str | None
) -> dict[str, str]:
    if not isinstance(evidence, VerifiedGatewayForwarding):
        raise GatewayTransportDenied("C2_FORWARDING_EVIDENCE_REQUIRED")
    now = datetime.now(UTC)
    if (
        evidence.target != target
        or evidence.method != method
        or not isinstance(evidence.expires_at, datetime)
        or evidence.expires_at.tzinfo is None
        or evidence.expires_at.utcoffset() is None
        or not now < evidence.expires_at <= now + timedelta(seconds=120)
        or any(
            not isinstance(u, UUID) or u.version != 4
            for u in (evidence.recipient_service_id, evidence.recipient_instance_uuid)
        )
    ):
        raise GatewayTransportDenied("C2_FORWARDING_SCOPE_INVALID")
    if method in {"POST", "PUT", "PATCH", "DELETE"} and (
        evidence.operation_uuid is None
        or evidence.operation_uuid.version != 4
        or original != str(evidence.operation_uuid)
    ):
        raise GatewayTransportDenied("ORIGINAL_OPERATION_BINDING_REQUIRED")
    forwarded: dict[str, str] = {}
    for name, value in evidence.headers:
        if not isinstance(name, str) or not isinstance(value, str):
            raise GatewayTransportDenied("C2_HEADER_SET_INVALID")
        key = name.casefold()
        if (
            key not in _SAFE_FORWARD
            or key in forwarded
            or "\r" in value
            or "\n" in value
            or not value.isascii()
        ):
            raise GatewayTransportDenied("C2_HEADER_SET_INVALID")
        if key == "cookie" and target != "panel":
            raise GatewayTransportDenied("COOKIE_MUST_REMAIN_PANEL_SCOPED")
        if key == "authorization" and target == "panel":
            raise GatewayTransportDenied("PANEL_MUST_NOT_RECEIVE_OWNER_BEARER")
        if key in {"mcp-session-id", "mcp-protocol-version", "last-event-id"} and target in {
            "panel",
            "api",
        }:
            raise GatewayTransportDenied("MCP_SESSION_MUST_REMAIN_RESOURCE_SCOPED")
        forwarded[key] = value
    if method in {"POST", "PUT", "PATCH", "DELETE"} and (
        forwarded.get("operation-uuid") != original or forwarded.get("idempotency-key") != original
    ):
        raise GatewayTransportDenied("SIGNED_ORIGINAL_HEADERS_REQUIRED")
    # Browser-supplied Forwarded, Authorization, Cookie and C2 service identity
    # are NEVER copied by this module. Only already-verified port output used.
    forwarded["host"] = f"{PRIVATE_UPSTREAMS[target][0]}:{PRIVATE_UPSTREAMS[target][1]}"
    return forwarded


def require_fresh_forwarding(
    initial: VerifiedGatewayForwarding,
    refreshed: object,
    *,
    target: GatewayTarget,
    method: str,
    original: str | None,
) -> dict[str, str]:
    """Deny altered original assertions and truncated current grant lifetime.

    A18 revalidate_current is a read-only verifier of CURRENT owner state,
    never a second JTI consumer or an authority to change source headers.
    """
    if not isinstance(refreshed, VerifiedGatewayForwarding):
        raise GatewayTransportDenied("CURRENT_OWNER_GRANT_REQUIRED")
    if (
        refreshed.target != initial.target
        or refreshed.method != initial.method
        or refreshed.operation_uuid != initial.operation_uuid
        or refreshed.recipient_service_id != initial.recipient_service_id
        or refreshed.recipient_instance_uuid != initial.recipient_instance_uuid
        or refreshed.headers != initial.headers
        or not isinstance(initial.expires_at, datetime)
        or initial.expires_at.tzinfo is None
        or initial.expires_at.utcoffset() is None
        or not isinstance(refreshed.expires_at, datetime)
        or refreshed.expires_at.tzinfo is None
        or refreshed.expires_at.utcoffset() is None
        or refreshed.expires_at > initial.expires_at
    ):
        raise GatewayTransportDenied("CURRENT_OWNER_GRANT_CHANGED")
    return require_forwarding(refreshed, target=target, method=method, original=original)


def _private_url(route: GatewayRoute, query: bytes) -> str:
    if len(query) > 8192 or not _STRICT_QUERY.fullmatch(query) or b"#" in query:
        raise GatewayTransportDenied("INVALID_BOUNDED_QUERY")
    if any(
        len(part) < 2 or any(ch not in b"0123456789ABCDEFabcdef" for ch in part[:2])
        for part in query.split(b"%")[1:]
    ):
        raise GatewayTransportDenied("INVALID_QUERY_PERCENT_ENCODING")
    host, port = PRIVATE_UPSTREAMS[route.target]
    quoted_path = quote(route.upstream_path, safe="/-._~")
    return f"http://{host}:{port}{quoted_path}" + ("?" + query.decode("ascii") if query else "")


def _safe_redirect_location(response: httpx.Response, route: GatewayRoute) -> str:
    """Rebase one private Panel/API path into its own public namespace.

    Never emit upstream DNS, scheme, port, authority, credentials, fragments,
    hidden encoded paths or a redirect across Panel/API resource boundaries.
    Unapproved OAuth/cookie redirects intentionally remain unavailable.
    """
    if route.target not in {"panel", "api"} or route.public_static:
        raise GatewayTransportDenied("STATIC_OR_MCP_REDIRECT_NOT_AUTHORIZED")
    locations = response.headers.get_list("location")
    if len(locations) != 1:
        raise GatewayTransportDenied("REDIRECT_LOCATION_MISSING_OR_AMBIGUOUS")
    raw = locations[0]
    if (
        not isinstance(raw, str)
        or len(raw) > 2048
        or not raw.isascii()
        or any(ord(char) < 33 or ord(char) == 127 for char in raw)
        or "\\" in raw
        or "%" in raw
    ):
        raise GatewayTransportDenied("REDIRECT_LOCATION_UNSAFE")
    try:
        location = urlsplit(raw)
    except ValueError as exc:
        raise GatewayTransportDenied("REDIRECT_LOCATION_UNPARSABLE") from exc
    if (
        location.scheme
        or location.netloc
        or location.fragment
        or not location.path.startswith("/")
        or location.path.startswith("//")
        or "//" in location.path
        or any(part in {".", ".."} for part in location.path.split("/"))
    ):
        raise GatewayTransportDenied("REDIRECT_ORIGIN_OR_PATH_REJECTED")
    query = location.query.encode("ascii")
    if len(query) > 2048 or not _STRICT_QUERY.fullmatch(query) or b"#" in query or b"@" in query:
        raise GatewayTransportDenied("REDIRECT_QUERY_UNSAFE")
    prefix = f"/{route.target}"
    if location.path == prefix or location.path.startswith(prefix + "/"):
        # Nginx's relative /panel/ redirect and API's own prefixed routes
        # already contain the prefix. Never produce /panel/panel/.
        public_path = location.path
    else:
        if location.path.split("/")[1] in {
            "panel",
            "api",
            "hands",
            ".well-known",
            "oauth",
            "_site",
        }:
            raise GatewayTransportDenied("REDIRECT_CROSSED_ROUTE_SCOPE")
        public_path = prefix + location.path
    resolved = route_for_path(public_path)
    if resolved is None or resolved.target != route.target:
        raise GatewayTransportDenied("REDIRECT_CROSSED_ROUTE_SCOPE")
    return public_path + ("?" + location.query if query else "")


def _response_headers(headers: httpx.Headers, target: GatewayTarget) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in headers.multi_items():
        name = key.casefold()
        if name in _RESPONSE_DENY:
            continue
        if name not in {
            "content-type",
            "content-encoding",
            "cache-control",
            "etag",
            "last-modified",
            "vary",
            "retry-after",
            "mcp-session-id",
            "mcp-protocol-version",
            "x-request-id",
        }:
            continue
        values[name] = value
    # No backend Location or Set-Cookie is promoted onto public origin until
    # approved browser cookie-domain/path/redirect rewriting and CSRF policy.
    values.setdefault("cache-control", "no-store")
    if target not in {"panel", "api"}:
        values.pop("etag", None)
    return values


class PrivateGatewayTransport:
    """Installed only with independently validated C2 + D6 network release."""

    def __init__(
        self,
        *,
        source: TrustedGatewaySourcePort | None = None,
        websocket_dialer: TrustedWebSocketDialer | None = None,
        public_static_enabled: bool = False,
        max_in_flight: int = 32,
    ) -> None:
        if not 1 <= max_in_flight <= 256:
            raise ValueError("bounded gateway concurrency required")
        self.source = source
        if type(public_static_enabled) is not bool:
            raise ValueError("public static release gate must be explicit")
        self.websocket_dialer = websocket_dialer
        self.public_static_enabled = public_static_enabled
        self._slots = asyncio.Semaphore(max_in_flight)
        self._client: httpx.AsyncClient | None = None
        self._draining = False
        self._open_responses: set[httpx.Response] = set()
        self._all_closed = asyncio.Event()
        self._all_closed.set()
        self._static_in_flight = 0
        self._all_static_closed = asyncio.Event()
        self._all_static_closed.set()
        self._active_ws: set[asyncio.Task[None]] = set()
        self._all_ws_closed = asyncio.Event()
        self._all_ws_closed.set()

    @asynccontextmanager
    async def lifespan(self, _app: Starlette) -> AsyncIterator[None]:
        # Default closed Gateway has no public listener or upstream pool.
        # A separately accepted D6 static-only release may opt into public
        # GET/HEAD even while protected A18/C2 source remains unconfigured.
        if self.source is None and not self.public_static_enabled:
            yield
            return
        self._draining = False
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            self._client = client
            try:
                yield
            finally:
                self._draining = True
                try:
                    async with asyncio.timeout(10):
                        await asyncio.gather(
                            self._all_closed.wait(), self._all_static_closed.wait()
                        )
                except TimeoutError:
                    pass
                for response in tuple(self._open_responses):
                    await response.aclose()
                self._open_responses.clear()
                self._all_closed.set()
                try:
                    async with asyncio.timeout(10):
                        await self._all_ws_closed.wait()
                except TimeoutError:
                    for task in tuple(self._active_ws):
                        task.cancel()
                    await asyncio.gather(*self._active_ws, return_exceptions=True)
                self._client = None

    def _current_client(self) -> httpx.AsyncClient | None:
        """Read pool state anew after async grant verification/drain racing."""
        return self._client

    @staticmethod
    def _denied() -> Response:
        return JSONResponse(
            {"code": "GATEWAY_C2_RELEASE_UNAVAILABLE"},
            status_code=503,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    async def public_static(self, request: Request, route: GatewayRoute) -> Response:
        """Only the three owner-approved public files; never consume C2/JTI.

        Public release is an explicit operator-injected source flag, disabled
        in the default entrypoint and the current D6 protected exit78 image.
        No caller cookie, bearer, forwarded header, query, or body is passed
        into the existing private Nginx static server.
        """
        if (
            not self.public_static_enabled
            or route.target != "panel"
            or not route.public_static
            or route.public_path not in _PUBLIC_STATIC_PATHS
            or route.upstream_path != route.public_path
            or request.method not in {"GET", "HEAD"}
            or request.scope.get("raw_path") != route.public_path.encode("ascii")
            or request.scope.get("query_string", b"")
            or self._draining
        ):
            return self._denied()
        client = self._current_client()
        if client is None:
            return self._denied()
        acquired = False
        counted = False
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
            acquired = True
            if self._draining:
                raise GatewayTransportDenied("GATEWAY_DRAINING")
            self._static_in_flight += 1
            counted = True
            self._all_static_closed.clear()
            client = self._current_client()
            if client is None:
                raise GatewayTransportDenied("PUBLIC_STATIC_POOL_UNAVAILABLE")
            url = _private_url(route, b"")
            host, port = PRIVATE_UPSTREAMS["panel"]
            headers = {
                "host": f"{host}:{port}",
                "accept": "*/*",
                "accept-encoding": "identity",
            }
            # Entire static fetch/read is bounded; a misconfigured private
            # service cannot hold an infinite stream or become a public API.
            async with asyncio.timeout(8):
                upstream = await client.send(
                    client.build_request(request.method, url, headers=headers),
                    stream=True,
                )
                try:
                    if upstream.status_code != 200:
                        raise GatewayTransportDenied("PUBLIC_STATIC_NOT_READY")
                    expected = {
                        "/": ("text/html",),
                        "/robots.txt": ("text/plain",),
                        "/sitemap.xml": ("application/xml", "text/xml"),
                    }[route.public_path]
                    content_type = upstream.headers.get("content-type", "")
                    if (
                        not any(
                            content_type.casefold().split(";", 1)[0].strip() == item
                            for item in expected
                        )
                        or "noindex" in upstream.headers.get("x-robots-tag", "").casefold()
                    ):
                        raise GatewayTransportDenied("PUBLIC_STATIC_TYPE_OR_INDEX_INVALID")
                    if upstream.headers.get("content-encoding", "identity").casefold() not in {
                        "",
                        "identity",
                    }:
                        raise GatewayTransportDenied("PUBLIC_STATIC_ENCODING_UNSAFE")
                    raw_size = upstream.headers.get("content-length")
                    if raw_size is not None and not 0 <= int(raw_size) <= _MAX_PUBLIC_STATIC_BYTES:
                        raise GatewayTransportDenied("PUBLIC_STATIC_TOO_LARGE")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in upstream.aiter_raw():
                        size += len(chunk)
                        if size > _MAX_PUBLIC_STATIC_BYTES:
                            raise GatewayTransportDenied("PUBLIC_STATIC_TOO_LARGE")
                        chunks.append(chunk)
                finally:
                    await upstream.aclose()
            return Response(
                content=b"" if request.method == "HEAD" else b"".join(chunks),
                status_code=200,
                headers={
                    "Content-Type": content_type,
                    "Cache-Control": "public, max-age=60",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never echo a private static-server exception or URL to crawlers.
            return JSONResponse(
                {"code": "GATEWAY_PUBLIC_STATIC_UNAVAILABLE"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        finally:
            if counted:
                self._static_in_flight -= 1
                if not self._static_in_flight:
                    self._all_static_closed.set()
            if acquired:
                self._slots.release()

    async def http(self, request: Request) -> Response:
        route = route_for_path(request.url.path)
        if route is None:
            return self._denied()
        if route.public_static:
            return await self.public_static(request, route)
        if self.source is None or self._client is None or self._draining:
            return self._denied()
        if route.original_mcp and request.scope.get("raw_path") != route.public_path.encode(
            "ascii"
        ):
            # No encoded Files spelling, trailing-slash alias or path remap.
            return self._denied()
        length: int | None = None
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            declared_length = request.headers.get("content-length")
            if declared_length is not None:
                try:
                    length = int(declared_length)
                except ValueError:
                    length = -1
                if not 0 <= length <= _MAX_REQUEST_BYTES:
                    return JSONResponse({"code": "GATEWAY_BODY_BOUNDS_REQUIRED"}, status_code=413)
            # Chunked requests without a declared length remain bounded by
            # the actual byte counter below; never await an unbounded body().
        acquired = False
        try:
            # No User/Service principal accepted from unsigned header or JSON.
            async with asyncio.timeout(5):
                grant = await self.source.require_current(
                    request, target=route.target, method=request.method
                )
            original = request.headers.get("operation-uuid")
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                keys = [
                    value
                    for name, value in request.scope.get("headers", [])
                    if name.lower() in {b"operation-uuid", b"idempotency-key"}
                ]
                if (
                    len(keys) != 2
                    or not original
                    or request.headers.get("idempotency-key") != original
                ):
                    raise GatewayTransportDenied("ORIGINAL_HEADER_IDENTITY_REQUIRED")
            forwarded = require_forwarding(
                grant, target=route.target, method=request.method, original=original
            )
            # A cookie-backed state change needs the real same-origin browser
            # Origin plus a trusted Backend-bound CSRF token, not one copied
            # from an untrusted request header.
            if (
                request.method in {"POST", "PUT", "PATCH", "DELETE"}
                and route.target in {"panel", "api"}
                and "cookie" in forwarded
                and (
                    request.headers.get("origin") != PUBLIC_ORIGIN
                    or "x-csrf-token" not in forwarded
                )
            ):
                raise GatewayTransportDenied("COOKIE_CSRF_ORIGIN_REQUIRED")
            target_url = _private_url(route, request.scope.get("query_string", b""))
            body = b""
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                chunks: list[bytes] = []
                count = 0
                # Slow uploads cannot hold a historical signed grant open.
                # This timeout covers the entire request body, not each chunk.
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        count += len(chunk)
                        if count > _MAX_REQUEST_BYTES:
                            raise GatewayTransportDenied("GATEWAY_BODY_TOO_LARGE")
                        chunks.append(chunk)
                if length is not None and count != length:
                    raise GatewayTransportDenied("CONTENT_LENGTH_MISMATCH")
                body = b"".join(chunks)
            # Bounded semaphore is HELD until the last SSE / Streamable HTTP
            # chunk is consumed or the downstream client disconnects.
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
            acquired = True
            # RECHECK at the private send boundary AFTER uploading the body
            # and waiting for capacity. A18 must implement this as a READ-ONLY
            # current owner/grant/fence/JTI check; never consume JTI twice.
            if self._draining or self._client is None:
                raise GatewayTransportDenied("GATEWAY_DRAINING")
            body_sha256 = (
                hashlib.sha256(body).hexdigest()
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}
                else None
            )
            async with asyncio.timeout(5):
                refreshed = await self.source.revalidate_current(
                    request, previous=grant, body_sha256=body_sha256
                )
            forwarded = require_fresh_forwarding(
                grant,
                refreshed,
                target=route.target,
                method=request.method,
                original=original,
            )
            if refreshed.expires_at <= datetime.now(UTC) + timedelta(seconds=10):
                raise GatewayTransportDenied("CURRENT_OWNER_GRANT_TOO_CLOSE_TO_EXPIRY")
        except asyncio.CancelledError:
            if acquired:
                self._slots.release()
            raise
        except (TimeoutError, GatewayTransportDenied, ValueError, TypeError):
            if acquired:
                self._slots.release()
            return self._denied()
        except Exception:
            if acquired:
                self._slots.release()
            return self._denied()
        client = self._current_client()
        if client is None:
            self._slots.release()
            return self._denied()
        try:
            backend_request = client.build_request(
                request.method, target_url, headers=forwarded, content=body
            )
            response = await client.send(backend_request, stream=True)
        except httpx.HTTPError:
            self._slots.release()
            return JSONResponse({"code": "GATEWAY_PRIVATE_UPSTREAM_UNAVAILABLE"}, status_code=502)
        except BaseException:
            self._slots.release()
            raise

        # HTTP redirects never leak a private Docker DNS name, private cookie,
        # or off-scope URL. Unsafe and malformed 3xx fail with a typed 502.
        if 300 <= response.status_code < 400 and response.status_code != 304:
            try:
                location = _safe_redirect_location(response, route)
            except GatewayTransportDenied:
                return_response: Response = JSONResponse(
                    {"code": "GATEWAY_REDIRECT_REJECTED"},
                    status_code=502,
                    headers={"Cache-Control": "no-store"},
                )
            else:
                return_response = Response(
                    status_code=response.status_code,
                    headers={
                        **_response_headers(response.headers, route.target),
                        "location": location,
                    },
                )
            finally:
                await response.aclose()
                self._slots.release()
            return return_response

        self._open_responses.add(response)
        self._all_closed.clear()
        released = False

        async def finish() -> None:
            nonlocal released
            if released:
                return
            released = True
            try:
                await response.aclose()
            finally:
                self._open_responses.discard(response)
                if not self._open_responses:
                    self._all_closed.set()
                self._slots.release()

        async def streamed() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_raw():
                    # Starlette sends each chunk before requesting the next,
                    # preserving downstream backpressure and cancellation.
                    yield chunk
            finally:
                await finish()

        return StreamingResponse(
            streamed(),
            status_code=response.status_code,
            headers=_response_headers(response.headers, route.target),
            media_type=None,
            background=BackgroundTask(finish),
        )

    async def websocket(self, socket: WebSocket) -> None:
        # No WebSocket upgrade until BOTH current C2 and private dialer exist.
        route = route_for_path(socket.url.path)
        if (
            route is None
            or route.public_static
            or (
                route.original_mcp
                and socket.scope.get("raw_path") != route.public_path.encode("ascii")
            )
        ):
            await socket.close(code=1008)
            return
        if self.source is None or self.websocket_dialer is None or self._draining:
            await socket.close(code=1008)
            return
        acquired = False
        try:
            async with asyncio.timeout(5):
                grant = await self.source.require_current(
                    socket, target=route.target, method="WEBSOCKET"
                )
            forwarded = require_forwarding(
                grant, target=route.target, method="WEBSOCKET", original=None
            )
            query = socket.scope.get("query_string", b"")
            _private_url(route, query)
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
            acquired = True
            if self._draining:
                raise GatewayTransportDenied("GATEWAY_DRAINING")
            async with asyncio.timeout(5):
                refreshed = await self.source.revalidate_current(
                    socket, previous=grant, body_sha256=None
                )
            forwarded = require_fresh_forwarding(
                grant, refreshed, target=route.target, method="WEBSOCKET", original=None
            )
            if refreshed.expires_at <= datetime.now(UTC) + timedelta(seconds=10):
                raise GatewayTransportDenied("CURRENT_OWNER_GRANT_TOO_CLOSE_TO_EXPIRY")
        except asyncio.CancelledError:
            if acquired:
                self._slots.release()
            raise
        except Exception:
            if acquired:
                self._slots.release()
            await socket.close(code=1008)
            return
        current = asyncio.current_task()
        if current is not None:
            self._active_ws.add(current)
            self._all_ws_closed.clear()
        try:
            async with self.websocket_dialer.connect(route, forwarded, query) as upstream:
                await socket.accept()

                async def upstream_writer() -> None:
                    while True:
                        message = await socket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        if message["type"] != "websocket.receive":
                            raise GatewayTransportDenied("WS_FRAME_NOT_ACCEPTED")
                        payload = message.get("bytes")
                        if payload is None:
                            text = message.get("text")
                            if (
                                not isinstance(text, str)
                                or len(text.encode()) > _MAX_WS_MESSAGE_BYTES
                            ):
                                raise GatewayTransportDenied("WS_FRAME_TOO_LARGE")
                            await upstream.send_text(text)
                        else:
                            if len(payload) > _MAX_WS_MESSAGE_BYTES:
                                raise GatewayTransportDenied("WS_FRAME_TOO_LARGE")
                            await upstream.send_bytes(payload)

                async def upstream_reader() -> None:
                    while True:
                        payload = await upstream.receive()
                        if isinstance(payload, str):
                            if len(payload.encode()) > _MAX_WS_MESSAGE_BYTES:
                                raise GatewayTransportDenied("WS_FRAME_TOO_LARGE")
                            await socket.send_text(payload)
                        else:
                            if len(payload) > _MAX_WS_MESSAGE_BYTES:
                                raise GatewayTransportDenied("WS_FRAME_TOO_LARGE")
                            await socket.send_bytes(payload)

                # First close/disconnect cancels the opposite direction,
                # avoiding orphaned upstream sockets and runaway tasks.
                tasks = [
                    asyncio.create_task(upstream_writer()),
                    asyncio.create_task(upstream_reader()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    if not task.cancelled() and task.exception() is not None:
                        raise GatewayTransportDenied("WS_PRIVATE_CHANNEL_UNAVAILABLE")
                await upstream.close(code=1000)
        except (WebSocketDisconnect, GatewayTransportDenied, OSError):
            await socket.close(code=1008)
        except Exception:
            await socket.close(code=1011)
        finally:
            if current is not None:
                self._active_ws.discard(current)
                if not self._active_ws:
                    self._all_ws_closed.set()
            self._slots.release()

    def routes(self) -> list[Route | WebSocketRoute]:
        # Explicit static P0 namespaces, no alias, no catch-all Hands route.
        result: list[Route | WebSocketRoute] = [
            Route("/", self.http, methods=_ALLOWED_METHODS),
            Route("/robots.txt", self.http, methods=_ALLOWED_METHODS),
            Route("/sitemap.xml", self.http, methods=_ALLOWED_METHODS),
            Route("/panel", self.http, methods=_ALLOWED_METHODS),
            Route("/panel/{path:path}", self.http, methods=_ALLOWED_METHODS),
            Route("/api", self.http, methods=_ALLOWED_METHODS),
            Route("/api/{path:path}", self.http, methods=_ALLOWED_METHODS),
            WebSocketRoute("/panel/{path:path}", self.websocket),
            WebSocketRoute("/api/{path:path}", self.websocket),
        ]
        result.extend(
            Route(path, self.http, methods=_ALLOWED_METHODS) for path in MCP_ENDPOINTS.values()
        )
        return result
