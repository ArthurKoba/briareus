"""Isolated greenfield Admin app. NOT the legacy Admin API runtime.

The preview can only be enabled on local loopback without proxies. This is
NOT C1-B2/C2 public API acceptance: external HTTPS, OAuth identity, service
provenance and deploy integration remain explicit orchestration gates.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from api_errors import api_error, install_admin_api_error_handlers
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from presentation.platform_api import build_unmounted_platform_router
from pydantic import Field, field_validator
from sqlalchemy import text
from starlette.responses import Response

from authorization.platform_composition import (
    PlatformServices,
    compose_platform,
    platform_metadata,
)
from common.platform_db import PlatformDatabaseSettings
from common.settings import ProcessSettings

logger = logging.getLogger(__name__)

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


class PlatformPreviewSettings(ProcessSettings):
    enabled: bool = Field(False, validation_alias="PLATFORM_ADMIN_PREVIEW_ENABLED")
    ui_origin: str = Field("", validation_alias="PLATFORM_ADMIN_PREVIEW_UI_ORIGIN")
    emit_system_invitation: bool = Field(
        False, validation_alias="PLATFORM_ADMIN_PREVIEW_LOG_SYSTEM_INVITE"
    )

    @field_validator("ui_origin")
    @classmethod
    def _loopback_origin(cls, value: str) -> str:
        if not value:
            return ""
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in _LOOPBACK
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("preview UI origin must be a loopback HTTP(S) origin")
        return value.rstrip("/")


def _loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _private_preview_request(request: Request) -> bool:
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


def create_platform_admin_app(
    preview_settings: PlatformPreviewSettings | None = None,
) -> FastAPI:
    """Build an isolated disabled-by-default API with no automatic DB DDL."""
    cfg = preview_settings or PlatformPreviewSettings()
    services: PlatformServices | None = None

    # Instantiate only after explicit preview opt-in; failure is fail-closed.
    if cfg.enabled:
        services = compose_platform(PlatformDatabaseSettings())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            try:
                # Verify only the expected clean schema exists. Never create
                # or upgrade tables on startup.
                async with services.database.engine.connect() as connection:
                    database_name = await connection.scalar(text("SELECT current_database()"))
                    if not isinstance(database_name, str) or not database_name.endswith("_dev"):
                        raise RuntimeError("Admin preview requires a dedicated disposable *_dev DB")
                    for table in platform_metadata().sorted_tables:
                        relation = await connection.scalar(
                            text("SELECT to_regclass(:name)"),
                            {"name": table.fullname},
                        )
                        if relation is None:
                            raise RuntimeError(
                                "Admin preview schema incomplete; dev baseline required"
                            )
                if cfg.emit_system_invitation:
                    # Explicit operator-only preview setting; startup logging of
                    # registration URL is a deliberately sensitive product choice.
                    invitation_url = await services.identity.system_registration_link()
                    logger.warning(
                        "platform system invitation URL (operator-only): %s", invitation_url
                    )
                yield
            finally:
                await services.database.close()
        else:
            yield

    app = FastAPI(
        title="MCP Bridge Project Administration (draft)",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    if cfg.enabled and services is not None:
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
        if cfg.ui_origin:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=[cfg.ui_origin],
                allow_credentials=False,  # Authorization bearer, NEVER cookie auth
                allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "Idempotency-Key",
                    "If-Match-Version",
                ],
                expose_headers=["X-Request-ID", "Retry-After"],
            )

    install_admin_api_error_handlers(app)

    def _private_failure(code: int, reason: str) -> Response:
        response = api_error(code, reason)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.middleware("http")
    async def preview_perimeter(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Even when someone changes the ASGI target/host, a remote client never
        # receives a project endpoint. C2 must deliberately revise this gate.
        if not _private_preview_request(request):
            return _private_failure(403, "private preview only")
        if not cfg.enabled and request.url.path != "/health/live":
            return _private_failure(503, "platform Admin not enabled")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin is not None and (not cfg.ui_origin or origin != cfg.ui_origin):
                return _private_failure(403, "origin rejected")
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health/live", include_in_schema=False)
    async def liveness() -> dict[str, bool]:
        return {"service": bool(cfg.enabled)}

    return app


# A separate ASGI target; legacy runtime imports neither this app nor its
# security context. Without explicit local preview opt-in only health exists.
app = create_platform_admin_app()
