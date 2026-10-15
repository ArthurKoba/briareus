"""Private Hand HTTP with real safe diagnostics and closed protected effects."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from ._diagnostics import ProtectedHandTools

_ALLOWED_HTTP_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def create_diagnostic_hand_app(
    *,
    unavailable_code: str,
    health_fields: Mapping[str, str] | None = None,
    hand: str | None = None,
    source_root: Path | None = None,
    protected_tools: ProtectedHandTools | None = None,
) -> Starlette:
    """Default liveness-only Hand; protected registration requires trusted injection."""
    if not unavailable_code or any(char.isspace() for char in unavailable_code):
        raise ValueError("unavailable_code must be a nonempty code token")
    if (hand is None) != (source_root is None):
        raise ValueError("Hand name and source root must be provided together")
    if protected_tools is not None and (
        hand is None or not isinstance(protected_tools, ProtectedHandTools)
    ):
        raise ValueError("protected Hand tools require a named trusted composition root")
    catalog: dict[str, object] | None = None
    if hand is not None and source_root is not None:
        from ._catalog import source_capabilities

        catalog = source_capabilities(hand, source_root / "modules")
    diagnostic_app = None
    if catalog is not None:
        from fastmcp.server.http import HostOriginGuardMiddleware

        from ._diagnostics import diagnostic_mcp
        from ._effect_auth import ResourceTrust

        trust = ResourceTrust.from_environment(hand)
        mcp = diagnostic_mcp(
            hand,
            catalog,
            resource_verifier=trust.verifier() if trust is not None else None,
            protected_tools=protected_tools,
        )
        allowed_mcp_hosts = [
            f"briareus-{hand}:8000",
            "127.0.0.1:8000",
            "localhost:8000",
        ]
        catalog["mcp_transport"] = "resource_auth_staged" if trust else "diagnostic_only"
        if protected_tools is not None:
            # Source inventory is NOT a proof that owner-backed effects are
            # ready. Distinguish injected-but-unaccepted ports from the
            # default genuinely disabled application.
            catalog["authorization"] = "resource_verifier_configured_unaccepted"
            catalog["execution"] = "owner_ports_injected_unaccepted"
        diagnostic_app = mcp.http_app(
            path="/mcp",
            stateless_http=True,
            json_response=True,
            host_origin_protection=True,
            allowed_hosts=allowed_mcp_hosts,
        )
    health_info = {"state": "live", "mcp": catalog["mcp_transport"] if catalog else "not_mounted"}
    if health_fields:
        health_info.update(health_fields)

    async def health(_request: Request) -> Response:
        return JSONResponse(health_info)

    async def readiness(_request: Request) -> Response:
        # A live private process is not an authorized or registered MCP Hand.
        return JSONResponse(
            {
                "state": "not_ready",
                "mcp": catalog["mcp_transport"] if catalog else "not_mounted",
                "authorization": (
                    "owner_ports_injected_unaccepted" if protected_tools else "not_configured"
                ),
            },
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
    if diagnostic_app is not None:
        from ._effect_boundary import EffectBoundary

        # Check Host/Origin BEFORE the effect PEP reads identity/contacts PDP.
        # FastMCP's own middleware remains intact as the second guard.
        guarded_mcp = HostOriginGuardMiddleware(
            EffectBoundary(diagnostic_app), allowed_hosts=allowed_mcp_hosts, mode="strict"
        )
        routes.append(Route("/mcp", endpoint=guarded_mcp, methods=["POST", "DELETE"]))
    routes.extend(
        [
            Route("/", unavailable, methods=_ALLOWED_HTTP_METHODS),
            Route("/{path:path}", unavailable, methods=_ALLOWED_HTTP_METHODS),
            WebSocketRoute("/{path:path}", deny_ws),
        ]
    )
    return Starlette(
        routes=routes,
        lifespan=diagnostic_app.router.lifespan_context if diagnostic_app else None,
    )
