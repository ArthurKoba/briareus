"""One-origin, fail-closed Gateway source pending accepted real C2 ingress.

This ASGI entrypoint does not import the historical FastMCP registry. Each
future module transport must be reviewed against audience/JTI, current grant,
Host/Origin, original operation identity and long-lived streaming behavior.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware as ASGIMiddleware

from .gateway_transport import (
    PrivateGatewayTransport,
    TrustedGatewayPreauthPort,
    TrustedGatewaySourcePort,
    TrustedWebSocketDialer,
)
from .single_origin import SingleOriginGuard, unavailable_routes


def private_gateway_application(
    *,
    current_source: TrustedGatewaySourcePort | None = None,
    preauth_source: TrustedGatewayPreauthPort | None = None,
    websocket_dialer: TrustedWebSocketDialer | None = None,
    public_static_enabled: bool = False,
) -> Starlette:
    """No protected routes without A18 C2. Public static needs D6 opt-in.

    The default app never opens a client or public service listener. A D6
    source-accepted static-only release can opt into just GET/HEAD on the
    three owner-approved crawler-visible root files, independent of C2.
    """
    transport = PrivateGatewayTransport(
        source=current_source,
        preauth=preauth_source,
        websocket_dialer=websocket_dialer,
        public_static_enabled=public_static_enabled,
    )
    private_app = Starlette(
        routes=[*transport.routes(), *unavailable_routes()],
        middleware=[
            ASGIMiddleware(
                SingleOriginGuard,
                allow_verified_websocket=(
                    current_source is not None and websocket_dialer is not None
                ),
            )
        ],
        lifespan=transport.lifespan,
    )
    if current_source is None:
        # Without current A18 trust only the explicitly D6-released public
        # static reads may work. No FastMCP/provider/collector startup, no
        # protected route or signed JTI is implicitly enabled.
        return private_app
    from modules.project_runtime.runtime_telemetry import RuntimeTelemetry

    return RuntimeTelemetry.construct("gateway").attach(private_app)


app = private_gateway_application()

# R23 static-only release entrypoint. Protected API/Panel/Hands remain C2 denied.
static_app = private_gateway_application(public_static_enabled=True)
