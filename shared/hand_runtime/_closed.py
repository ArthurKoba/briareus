"""A fail-closed ASGI shell used until a Hand's OAuth/Cedar ports are verified."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

_ALLOWED_HTTP_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def create_closed_hand_app(
    *, unavailable_code: str, health_fields: Mapping[str, str] | None = None
) -> Starlette:
    """Health proves process liveness only; all protected access stays closed."""
    if not unavailable_code or any(char.isspace() for char in unavailable_code):
        raise ValueError("unavailable_code must be a nonempty code token")
    health_info = {"state": "live", "mcp": "not_mounted"}
    if health_fields:
        health_info.update(health_fields)

    async def health(_request: Request) -> Response:
        return JSONResponse(health_info)

    async def unavailable(_request: Request) -> Response:
        return JSONResponse(
            {"code": unavailable_code},
            status_code=503,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    async def deny_ws(socket: WebSocket) -> None:
        await socket.close(code=1008)

    return Starlette(
        routes=[
            Route("/health/live", health, methods=["GET", "HEAD"]),
            Route("/", unavailable, methods=_ALLOWED_HTTP_METHODS),
            Route("/{path:path}", unavailable, methods=_ALLOWED_HTTP_METHODS),
            WebSocketRoute("/{path:path}", deny_ws),
        ]
    )
