"""One-origin, fail-closed Gateway source pending accepted real C2 ingress.

This ASGI entrypoint does not import the historical FastMCP registry. Each
future module transport must be reviewed against audience/JTI, current grant,
Host/Origin, original operation identity and long-lived streaming behavior.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware as ASGIMiddleware

from modules.project_runtime.runtime_telemetry import RuntimeTelemetry

from .single_origin import SingleOriginGuard, unavailable_routes

_runtime_telemetry = RuntimeTelemetry.construct("gateway")


@asynccontextmanager
async def _gateway_lifespan(_app: Starlette) -> AsyncIterator[None]:
    # No legacy backend pools or OAuth bootstrap are created by this closed
    # ingress; no global owner DB, client, session manager or tool registration.
    yield


app = _runtime_telemetry.attach(
    Starlette(
        routes=unavailable_routes(),
        middleware=[ASGIMiddleware(SingleOriginGuard)],
        lifespan=_gateway_lifespan,
    )
)
