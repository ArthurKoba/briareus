"""P0 single public Gateway route contract (SOURCE only, deliberately closed).

No trusted auth/JTI, C2 owner peers, Panel/API upstream transports, WebSocket
upgrade/drain or streamable HTTP/SSE path have been accepted for this origin.
Until independently verified, these exact paths return a bounded unavailable
response and never proxy private services or advertise bogus OAuth metadata.
"""

from __future__ import annotations

from typing import Literal

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route
from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_ORIGIN = "https://briaray.koba-nexus.ru"
PUBLIC_HOST = "briaray.koba-nexus.ru"
MCP_MODULES: tuple[Literal["files", "web", "terminal", "svc", "infrastructure", "reverse"], ...] = (
    "files",
    "web",
    "terminal",
    "svc",
    "infrastructure",
    "reverse",
)
MCP_ENDPOINTS: dict[str, str] = {name: f"/hands/{name}/mcp" for name in MCP_MODULES}

# This is an allowlist, NOT an open-ended /hands/{module} proxy. The only
# source-accepted path for Files is /hands/files/mcp (plural).
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def unavailable(_request: Request) -> Response:
    """No streaming, echo, raw URL, credentials or arbitrary exception text."""
    return JSONResponse(
        {"code": "GATEWAY_C2_RELEASE_UNAVAILABLE"},
        status_code=503,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def unavailable_routes() -> list[BaseRoute]:
    """Static closed P0 namespaces; never mount historical MCP aliases."""
    return [
        Route("/", unavailable, methods=_METHODS),
        Route("/panel", unavailable, methods=_METHODS),
        Route("/panel/{path:path}", unavailable, methods=_METHODS),
        Route("/api", unavailable, methods=_METHODS),
        Route("/api/{path:path}", unavailable, methods=_METHODS),
        Route("/.well-known/oauth-authorization-server", unavailable, methods=_METHODS),
        Route("/.well-known/oauth-protected-resource", unavailable, methods=_METHODS),
        Route("/.well-known/openid-configuration", unavailable, methods=_METHODS),
        Route("/oauth/{path:path}", unavailable, methods=_METHODS),
        *[Route(path, unavailable, methods=_METHODS) for path in MCP_ENDPOINTS.values()],
    ]


class SingleOriginGuard:
    """Reject origin/Host spoofing before any later authenticated route install.

    This source guard never trusts x-forwarded-*, a caller-supplied JSON
    origin, or an arbitrary wildcard CORS entry. The accepted Traefik TLS
    termination and service-identity boundary must be separately verified.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        # Never drop non-ASCII bytes during Host/Origin decoding; lossy
        # replacement could accidentally turn malformed headers into a
        # trusted canonical hostname.
        try:
            hosts = [v.decode("ascii").casefold() for k, v in headers if k.lower() == b"host"]
            origins = [v.decode("ascii") for k, v in headers if k.lower() == b"origin"]
        except UnicodeDecodeError:
            hosts = []
            origins = ["malformed-origin"]
        host_allowed = len(hosts) == 1 and hosts[0] in {PUBLIC_HOST, f"{PUBLIC_HOST}:443"}
        origin_allowed = len(origins) <= 1 and (not origins or origins[0] == PUBLIC_ORIGIN)
        if not host_allowed or not origin_allowed:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await JSONResponse(
                    {"code": "GATEWAY_ORIGIN_REJECTED"},
                    status_code=421 if not host_allowed else 403,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
            return
        # A WebSocket upgrade must not silently become a public alternative
        # to signed MCP SSE/streamable HTTP and gateway C2 user approval.
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)
