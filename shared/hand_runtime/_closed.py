"""A fail-closed ASGI shell used until a Hand's OAuth/Cedar ports are verified."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

_ALLOWED_HTTP_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def create_closed_hand_app(
    *,
    unavailable_code: str,
    health_fields: Mapping[str, str] | None = None,
    hand: str | None = None,
    source_root: Path | None = None,
) -> Starlette:
    """Health proves process liveness only; all protected access stays closed."""
    if not unavailable_code or any(char.isspace() for char in unavailable_code):
        raise ValueError("unavailable_code must be a nonempty code token")
    if (hand is None) != (source_root is None):
        raise ValueError("Hand name and source root must be provided together")
    catalog: dict[str, object] | None = None
    if hand is not None and source_root is not None:
        from ._catalog import source_capabilities

        catalog = source_capabilities(hand, source_root / "modules")
    health_info = {"state": "live", "mcp": "not_mounted"}
    if health_fields:
        health_info.update(health_fields)

    async def health(_request: Request) -> Response:
        return JSONResponse(health_info)

    async def readiness(_request: Request) -> Response:
        # A live private process is not an authorized or registered MCP Hand.
        return JSONResponse(
            {"state": "not_ready", "mcp": "not_mounted", "authorization": "not_configured"},
            status_code=503,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    async def capabilities(_request: Request) -> Response:
        assert catalog is not None
        return JSONResponse(
            catalog,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    async def unavailable(_request: Request) -> Response:
        return JSONResponse(
            {"code": unavailable_code},
            status_code=503,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    async def deny_ws(socket: WebSocket) -> None:
        await socket.close(code=1008)

    routes = [
        Route("/health/live", health, methods=["GET", "HEAD"]),
        Route("/health/ready", readiness, methods=["GET", "HEAD"]),
    ]
    if catalog is not None:
        routes.append(Route("/internal/v1/capabilities", capabilities, methods=["GET", "HEAD"]))
    routes.extend(
        [
            Route("/", unavailable, methods=_ALLOWED_HTTP_METHODS),
            Route("/{path:path}", unavailable, methods=_ALLOWED_HTTP_METHODS),
            WebSocketRoute("/{path:path}", deny_ws),
        ]
    )
    return Starlette(routes=routes)
