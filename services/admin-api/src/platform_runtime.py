"""Briareus Admin API composition; trusted injection, not preview ENV toggles.

Without an approved C1-B2/C2 transport, only a direct-local, authenticated
service composition may expose operations. Default ASGI target serves health.
"""

from __future__ import annotations

import ipaddress
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from api_errors import api_error, install_admin_api_error_handlers
from fastapi import FastAPI, Request
from presentation.platform_api import build_unmounted_platform_router
from sqlalchemy import text
from starlette.responses import Response

from authorization.platform_composition import (
    PlatformServices,
    platform_metadata,
)

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

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            try:
                # Verify only the expected clean schema exists. Never create
                # or upgrade tables on startup.
                async with services.database.engine.connect() as connection:
                    database_name = await connection.scalar(text("SELECT current_database()"))
                    if not isinstance(database_name, str) or not database_name.endswith("_dev"):
                        raise RuntimeError("Admin requires a verified disposable *_dev DB")
                    for table in platform_metadata().sorted_tables:
                        relation = await connection.scalar(
                            text("SELECT to_regclass(:name)"),
                            {"name": table.fullname},
                        )
                        if relation is None:
                            raise RuntimeError(
                                "Admin schema incomplete; explicit dev initialization required"
                            )
                yield
            finally:
                await services.database.close()
        else:
            yield

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
        # Even when someone changes the ASGI target/host, a remote client never
        # receives a project endpoint. C2 must deliberately revise this gate.
        if not _private_request(request):
            return _private_failure(403, "verified local transport required")
        if services is None and request.url.path != "/health/live":
            return _private_failure(503, "Admin composition not provisioned")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin is not None:
                # C1-B2/C2 has not approved a cross-origin transport.
                # Same-origin requests have no cross-origin Origin requirements.

                return _private_failure(403, "origin rejected")
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health/live", include_in_schema=False)
    async def liveness() -> dict[str, bool]:
        return {"service": services is not None}

    return app


# The default ASGI target never interprets an ENV boolean as permission to
# mount Admin APIs; only an explicitly reviewed composition can do so.
app = create_platform_admin_app()
