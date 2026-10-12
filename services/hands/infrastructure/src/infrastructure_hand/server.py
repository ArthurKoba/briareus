"""Unprivileged health-only Infrastructure Hand while OAuth/Cedar is unavailable.

No service secrets, host process controls, privileged system operations or MCP
tools are installed. Real effects require independently verified Rauthy tokens
and a fresh authoritative Authorization/Cedar AgentSession decision.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def health(_request: Request) -> Response:
    return JSONResponse({"state": "live", "mcp": "not_mounted", "authorization": "not_configured"})


async def unavailable(_request: Request) -> Response:
    return JSONResponse(
        {"code": "INFRASTRUCTURE_OAUTH_AUTHORIZATION_UNAVAILABLE"},
        status_code=503,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def deny_ws(socket: WebSocket) -> None:
    await socket.close(code=1008)


app = Starlette(
    routes=[
        Route("/health/live", health, methods=["GET", "HEAD"]),
        Route("/", unavailable, methods=_METHODS),
        Route("/{path:path}", unavailable, methods=_METHODS),
        WebSocketRoute("/{path:path}", deny_ws),
    ]
)
