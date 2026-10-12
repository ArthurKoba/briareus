"""Safe private SVC Hand lifecycle pending verified provider/MCP admission.

SVC manages future GitHub/GitLab adapters, but this transitional cutover
mounts neither historical provider objects nor privileged MCP handlers.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def health(_request: Request) -> Response:
    """Internal process readiness, not an authenticated MCP acceptance."""
    return JSONResponse({"state": "live", "mcp": "not_mounted"})


async def unavailable(_request: Request) -> Response:
    return JSONResponse(
        {"code": "SVC_PRIVATE_C2_TRANSPORT_PENDING"},
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
