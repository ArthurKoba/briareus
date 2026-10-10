"""Briareus Authorization is the single automatic Alembic schema owner.

Normal ASGI startup first waits for the explicitly selected PostgreSQL
database, takes the migration coordinator's process-wide advisory lock,
upgrades checked-in Alembic revisions to one head and verifies the committed
schema. It NEVER creates schema by metadata.create_all or uses a second
migration App/CLI/sidecar.

C1-B2/C2 public Authorization identity is a separate gate. No legacy OAuth
routes, unverified header identities, Project tools or public Gateway mounts
are registered here. Liveness is NOT readiness; a verified schema alone
does not imply verified TLS/service signer/actor grants.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from common.platform_db import PlatformDatabase, PlatformDatabaseSettings
from common.platform_telemetry import BriareusHttpTelemetry

from .schema_migrations import (
    BriareusSchemaStatus,
    require_current_authorization_revision,
    run_authorization_schema_migrations,
)

logger = logging.getLogger("briareus.authorization")


@dataclass(frozen=True, slots=True)
class VerifiedAuthorizationIngress:
    """D4/C2 independently confirmed actual listener and signing authority."""

    signer_authority: str
    active_peer_transport: str
    expires_at: datetime


class TrustedAuthorizationIngressVerifier(Protocol):
    async def verify_running_ingress(self) -> VerifiedAuthorizationIngress:
        """Verify real listener, signed keys, peer IDs, grants and revocation."""
        ...


class AuthorizationReadiness(BaseModel):
    """No secret, DSN, actor/token, username or internal endpoint disclosure."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    service: str = "authorization"
    state: str = "starting"
    schema_revision: str | None = None
    tables_verified: int = Field(default=0, ge=0)
    migration_applied: bool = False
    security_ready: bool = False

    @property
    def ready(self) -> bool:
        return self.state == "ready" and self.schema_revision is not None and self.security_ready


def create_authorization_app(
    *,
    db_settings: PlatformDatabaseSettings | None = None,
    trusted_ingress: TrustedAuthorizationIngressVerifier | None = None,
) -> FastAPI:
    """Application factory; never enables public C1-B2/C2 via an ENV flag."""
    state = AuthorizationReadiness()
    runtime_db: PlatformDatabase | None = None
    telemetry: BriareusHttpTelemetry | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal state, runtime_db, telemetry
        state = AuthorizationReadiness(state="database_wait")
        # Settings are evaluated only during actual Authorization startup,
        # not when metadata, Alembic revision history or wheel is imported.
        settings = db_settings or PlatformDatabaseSettings()
        runtime_db = PlatformDatabase(settings)
        try:
            telemetry = BriareusHttpTelemetry("authorization")
            telemetry.started()
            state = AuthorizationReadiness(state="migrating")
            status: BriareusSchemaStatus = await run_authorization_schema_migrations(
                runtime_db, settings
            )
            state = AuthorizationReadiness(
                state="security_pending",
                schema_revision=status.revision,
                migration_applied=status.changed,
                tables_verified=status.table_count,
            )

            # Authorization is not ready for Gateway or Admin merely
            # because a DB version exists. Missing independent C2 listener
            # evidence denies readiness; it does not skip mandatory DDL.
            if trusted_ingress is not None:
                attestation = await trusted_ingress.verify_running_ingress()
                if (
                    not isinstance(attestation, VerifiedAuthorizationIngress)
                    or attestation.active_peer_transport not in {"mtls", "unix-peer"}
                    or not attestation.signer_authority
                    or attestation.expires_at.tzinfo is None
                    or attestation.expires_at <= datetime.now(UTC)
                ):
                    raise RuntimeError("Authorization trusted ingress attestation rejected")
                state = state.model_copy(update={"state": "ready", "security_ready": True})

            logger.info(
                "authorization schema verified revision=%s tables=%d trust=%s",
                status.revision,
                status.table_count,
                "verified" if state.ready else "not_configured",
            )
            yield
        except Exception:
            state = AuthorizationReadiness(state="failed")
            # ASGI exception tracebacks may contain DB connection parameters
            # or private service signer material. Propagate only fixed status.
            logger.error("Authorization startup failed; schema/trust not ready")
            raise RuntimeError(
                "Briareus Authorization unavailable: schema or trust unverified"
            ) from None
        finally:
            if telemetry is not None:
                telemetry.shutdown()
            if runtime_db is not None:
                await runtime_db.close()
            state = AuthorizationReadiness(state="stopped")

    app = FastAPI(
        title="Briareus Authorization",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def request_correlation(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # No request headers, body, raw paths, exception message or user
        # identities become telemetry attributes or returned trace context.
        correlation = str(uuid4())
        started_at = perf_counter()
        status_code = 500
        try:
            if request.url.path not in {"/health/live", "/health/ready", "/internal/schema-status"}:
                try:
                    await _require_current_ready()
                except HTTPException:
                    # ASGI user middleware runs outside FastAPI's error
                    # handler; return a real sanitized 503, not a raw 500.
                    response = Response(status_code=503, headers={"Cache-Control": "no-store"})
                    status_code = response.status_code
                    response.headers["X-Request-ID"] = correlation
                    return response
            if telemetry is None:
                response = await call_next(request)
            else:
                with telemetry.trace_request(
                    method=request.method, correlation_id=correlation
                ) as span:
                    response = await call_next(request)
                    if span is not None:
                        span.set_attribute("http.response.status_code", response.status_code)
            status_code = response.status_code
            response.headers["X-Request-ID"] = correlation
            response.headers["Cache-Control"] = "no-store"
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
    async def live() -> dict[str, str]:
        return {"service": "authorization"}

    async def _require_current_ready() -> AuthorizationReadiness:
        nonlocal state
        if not state.ready or runtime_db is None or trusted_ingress is None:
            raise HTTPException(
                status_code=503,
                detail="Authorization migration or trusted service ingress not ready",
            )
        try:
            await require_current_authorization_revision(runtime_db)
            # The initial C2 attestation may expire/revoke after ASGI startup.
            # Never promote a cached Ready bit into permanent service authority.
            peer = await trusted_ingress.verify_running_ingress()
            if (
                not isinstance(peer, VerifiedAuthorizationIngress)
                or peer.active_peer_transport not in {"mtls", "unix-peer"}
                or not peer.signer_authority
                or peer.expires_at.tzinfo is None
                or peer.expires_at <= datetime.now(UTC)
            ):
                raise RuntimeError("Authorization ingress attestation stale")
        except Exception:
            state = AuthorizationReadiness(state="failed")
            raise HTTPException(
                status_code=503,
                detail="Authorization migration or trusted service ingress not ready",
            ) from None
        return state

    @app.get("/health/ready", include_in_schema=False)
    async def ready() -> AuthorizationReadiness:
        return await _require_current_ready()

    @app.get("/internal/schema-status", include_in_schema=False)
    async def schema_status(request: Request) -> AuthorizationReadiness:
        # Until approved C2 peer transport exists, only direct loopback
        # management may observe version/status; forged forwarding headers
        # and public container network access cannot promote their origin.
        if request.client is None:
            raise HTTPException(status_code=403, detail="local status transport required")
        try:
            actual_peer = ipaddress.ip_address(request.client.host)
            host = request.url.hostname or ""
            same_host = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            raise HTTPException(
                status_code=403, detail="private status transport required"
            ) from None
        if (
            not actual_peer.is_loopback
            or not same_host
            or any(
                field in request.headers
                for field in (
                    "forwarded",
                    "x-forwarded-for",
                    "x-forwarded-host",
                    "x-forwarded-proto",
                    "x-real-ip",
                )
            )
        ):
            raise HTTPException(status_code=403, detail="private status transport required")
        return state

    return app


# Default D4 normal Authorization ASGI app. Environment settings are not
# read on import; migration is mandatory whenever its lifespan starts.
# C1-B2/C2 remains unready until a real verified ingress port is installed.
app = create_authorization_app()
