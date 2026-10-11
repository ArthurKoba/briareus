"""Single SVC private ASGI composition; all provider MCP actions fail closed.

This is the ONE source entrypoint for the GitHub+GitLab unit, but it is NOT a
physical C2-approved provider transport. D5 must retain active exit 78. Do
not mount either existing provider's historical `mcp` without independently
reviewed current service identity, consumed one-use JTI, Project/AgentSession
proof, signed command lifecycle and Catalog-custodied provider credentials.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from .composition import SVC_SOURCE_HANDLERS, PrivateSVCSourceSelector

# The typed selector exists for a future C2-authenticated composition. No
# default Project authority/source verifier is configured by this module.
# Source handlers are discoverable as exact registered module paths without
# importing historical AdminAPI credential clients or starting FastMCP here.
__all__ = ["SVC_SOURCE_HANDLERS", "PrivateSVCSourceSelector", "app"]

_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def _unavailable(_request: Request) -> Response:
    """Never echo a bearer, service ID, provider args, path or tool result."""
    return JSONResponse(
        {"code": "SVC_PRIVATE_C2_TRANSPORT_PENDING"},
        status_code=503,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def _deny_websocket(websocket: WebSocket) -> None:
    # No optional WS port may become a bypass for streamable HTTP auth/JTI.
    await websocket.close(code=1008)


@asynccontextmanager
async def _svc_lifespan(_app: Starlette) -> AsyncIterator[None]:
    """No provider clients/sessions/secrets are created or left to clean up."""
    yield


# These are private unavailable responses, NOT a FastMCP mount or proxy.
# No accepted authenticated transport, client session manager, Catalog
# credential redeemer or premature FastMCP/OTel exporter is installed.
# An accepted runtime transport must add audited per-tool OTel lifecycle.
# D5 current Docker CMD exit 78 stays.
app = Starlette(
    lifespan=_svc_lifespan,
    routes=[
        Route("/", _unavailable, methods=_METHODS),
        Route("/{path:path}", _unavailable, methods=_METHODS),
        WebSocketRoute("/{path:path}", _deny_websocket),
    ],
)
