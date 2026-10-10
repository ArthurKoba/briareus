"""Briareus Admin API composition; trusted injection, not preview ENV toggles.

Without an approved C1-B2/C2 transport, only a direct-local, authenticated
service composition may expose operations. Default ASGI target serves health.
"""

from __future__ import annotations

import ipaddress
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from api_errors import api_error, install_admin_api_error_handlers
from fastapi import FastAPI, Request
from presentation.platform_api import build_unmounted_platform_router
from starlette.responses import Response

from authorization.platform_composition import PlatformServices
from authorization.schema_migrations import (
    SchemaUpgradeRejected,
    require_current_authorization_revision,
    verify_authorization_schema_for_consumer,
)
from common.platform_telemetry import BriareusHttpTelemetry

# In this wave public operation remains blocked independently of configuration.
# To expose non-loopback interfaces requires a reviewed future C1-B2/C2 patch.
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_FORWARDED = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-real-ip",
    }
)


def _loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _private_request(request: Request) -> bool:
    bound = request.scope.get("server")
    if (
        request.client is None
        or not _loopback_host(request.client.host)
        or not isinstance(bound, tuple)
        or not bound
        or not isinstance(bound[0], str)
        or not _loopback_host(bound[0])
    ):
        return False
    if not _loopback_host(request.url.hostname or ""):
        return False
    # An ASGI app can still be placed behind a reverse proxy by an operator;
    # real deployment is blocked until C2 validates transport/provenance.
    return not any(key in request.headers for key in _FORWARDED)


def create_platform_admin_app(services: PlatformServices | None = None) -> FastAPI:
    """Injected, verified composition or health-only closed ASGI default."""
    telemetry: BriareusHttpTelemetry | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal telemetry
        if services is None:
            yield
            return
        try:
            # Admin is a READ-ONLY schema consumer, not a second migrator.
            # Authoritative version and all required constraints must
            # already be committed by Authorization on the selected DB.
            await verify_authorization_schema_for_consumer(services.database)
            telemetry = BriareusHttpTelemetry("admin-api")
            telemetry.started()
            yield
        finally:
            if telemetry is not None:
                telemetry.shutdown()
            await services.database.close()

    app = FastAPI(
        title="Briareus Project Administration",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    if services is not None:
        app.include_router(
            build_unmounted_platform_router(
                application=services.application,
                identity=services.identity,
                sessions=services.sessions,
                commands=services.commands,
                principal_resolver=services.admin_auth,
                resources=services.resources,
                local_auth=services.admin_auth,
            )
        )
    install_admin_api_error_handlers(app)

    def _private_failure(code: int, reason: str) -> Response:
        response = api_error(code, reason)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.middleware("http")
    async def protected_perimeter(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation = str(uuid4())
        started_at = perf_counter()
        status_code = 500

        async def securely_invoke() -> Response:
            # No reverse-proxy header is automatically trusted as caller
            # identity. A real C1-B2/C2 ingress must deliberately change
            # these gates after independently verified TLS/Origin.
            if not _private_request(request):
                return _private_failure(403, "verified local transport required")
            if services is None and request.url.path != "/health/live":
                return _private_failure(503, "Admin composition not provisioned")
            if services is not None and request.url.path != "/health/live":
                try:
                    # No long-lived admin process may keep serving stale
                    # bearer/role/Project logic after Authorization migrates
                    # the shared DB to a different accepted schema version.
                    await require_current_authorization_revision(services.database)
                except SchemaUpgradeRejected:
                    return _private_failure(503, "Authorization schema is not ready")
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if origin is not None:
                    return _private_failure(403, "origin rejected")
            return await call_next(request)

        try:
            if telemetry is not None:
                with telemetry.trace_request(
                    method=request.method,
                    correlation_id=correlation,
                ) as span:
                    response = await securely_invoke()
                    if span is not None:
                        span.set_attribute("http.response.status_code", response.status_code)
            else:
                response = await securely_invoke()
            status_code = response.status_code
            response.headers["X-Request-ID"] = correlation
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        finally:
            if telemetry is not None:
                telemetry.observe_http(
                    method=request.method,
                    status_code=status_code,
                    duration_ms=(perf_counter() - started_at) * 1000,
                )

    @app.get("/health/live", include_in_schema=False)
    async def liveness() -> dict[str, bool]:
        return {"service": services is not None}

    return app


# The default ASGI target never interprets an ENV boolean as permission to
# mount Admin APIs; only an explicitly reviewed composition can do so.
app = create_platform_admin_app()
