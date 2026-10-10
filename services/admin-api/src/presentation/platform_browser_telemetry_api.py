# ruff: noqa: B008  # FastAPI dependency descriptors in private draft
"""Private-only Briareus browser OTel relay. No collector token reaches JS.

Source contract for B14: authenticated same-origin TLS, current User JWT,
explicit opt-in, per-user and per-Project PostgreSQL rate quota, fixed enums
only and bounded application events. NOT mounted before C1-B2/C2 acceptance.
Old general frontend telemetry envelopes/paths are not accepted here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from telemetry_ingest import FrontendTelemetryProxy

from authorization._browser_telemetry import BrowserTelemetryAdmission
from authorization._idempotency import CommandOutcome, IdempotentCommandExecutor
from authorization._platform_application import PlatformApplication
from authorization._project_access import CallerPrincipal
from common.platform_errors import AccessDenied, AuthenticationRequired, InvalidInput
from common.platform_ids import PlatformProjectId

_MAX_BODY_BYTES = 16_384

bearer_scheme = HTTPBearer(auto_error=False)
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


class CurrentBrowserCaller(Protocol):
    async def resolve(self, request: Request) -> CallerPrincipal | None:
        """Resolve signed, unrevoked Briareus Admin JWT; never a raw UUID."""
        ...


class VerifiedBrowserOrigin(Protocol):
    async def require_attested_same_origin(
        self,
        request: Request,
        caller: CallerPrincipal,
    ) -> None:
        """Validate real HTTPS host and Origin, proxy trust, CSRF and referrer."""
        ...


class BrowserTelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["navigation", "http_failure", "render_error", "performance", "interaction"]
    component: Literal[
        "auth",
        "navigation",
        "project",
        "team",
        "users",
        "agents",
        "sessions",
        "resources",
        "settings",
    ]
    outcome: Literal["ok", "denied", "failed", "cancelled", "pending"]
    route_key: Literal[
        "login",
        "projects",
        "teams",
        "users",
        "agents",
        "sessions",
        "resources",
        "settings",
        "unknown",
    ]
    occurred_at: datetime
    duration_ms: int = Field(default=0, ge=0, le=300_000)

    @field_validator("occurred_at")
    @classmethod
    def _bounded_time(cls, value: datetime) -> datetime:
        now = datetime.now(UTC)
        if value.tzinfo is None or not (
            now - timedelta(minutes=5) <= value <= now + timedelta(minutes=1)
        ):
            raise ValueError("event timestamp outside accepted UTC window")
        return value


class BrowserTelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    project_id: UUID | None = None
    events: list[BrowserTelemetryEvent] = Field(min_length=1, max_length=32)

    @field_validator("project_id")
    @classmethod
    def _project_id(cls, value: UUID | None) -> UUID | None:
        if value is not None and value.version != 4:
            raise ValueError("project_id must be UUIDv4")
        return value


class BrowserTelemetryReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["queued"] = "queued"
    accepted_events: int = Field(ge=1, le=32)


class BrowserConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    confirmed: Literal[True]


class BrowserConsentView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool


async def _read_bounded_json(request: Request) -> tuple[bytes, int]:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="JSON browser telemetry required")
    header_size = request.headers.get("content-length")
    if header_size is not None:
        try:
            if int(header_size) > _MAX_BODY_BYTES or int(header_size) < 1:
                raise HTTPException(status_code=413, detail="browser telemetry size limit")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid content length") from None
    output = bytearray()
    async for chunk in request.stream():
        output.extend(chunk)
        if len(output) > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="browser telemetry size limit")
    if not output:
        raise InvalidInput("empty browser telemetry batch")
    return bytes(output), len(output)


def build_unmounted_browser_telemetry_router(
    app: PlatformApplication,
    commands: IdempotentCommandExecutor,
    caller_resolver: CurrentBrowserCaller,
    *,
    origin: VerifiedBrowserOrigin | None = None,
    exporter: FrontendTelemetryProxy | None = None,
) -> APIRouter:
    """D4/B14 must approve same-origin HTTPS + provider before mounting."""

    @asynccontextmanager
    async def private_exporter_lifespan(_router: APIRouter) -> AsyncIterator[None]:
        # The only permitted future mount takes ownership of the server-
        # side collector exporter. Flush/shutdown never runs in user request
        # transactions and never sends its bearer token to browser JavaScript.
        try:
            if exporter is not None:
                exporter.start()
            yield
        finally:
            if exporter is not None:
                await exporter.close()

    router = APIRouter(
        prefix="/v1/platform",
        tags=["private-browser-telemetry"],
        lifespan=private_exporter_lifespan,
    )
    admission = BrowserTelemetryAdmission(app)

    async def authenticated(
        request: Request,
        _bearer: Bearer,
    ) -> CallerPrincipal:
        if origin is None:
            raise AuthenticationRequired("verified same-origin browser channel not configured")
        # An explicitly presented bearer is mandatory: protocol wrappers
        # must not quietly resolve a legacy cookie, Basic credentials or
        # an unverified session User ID in a source-only relay.
        if (
            _bearer is None
            or _bearer.scheme.casefold() != "bearer"
            or not _bearer.credentials
        ):
            raise AuthenticationRequired("explicit verified Admin bearer required")
        principal = await caller_resolver.resolve(request)
        if principal is None:
            raise AuthenticationRequired("verified current Admin bearer required")
        # Consent GET/PUT and telemetry POST all require the SAME trusted
        # HTTPS host + Origin and current bearer. No side route may allow
        # consent changes across origins before the C2 browser review.
        await origin.require_attested_same_origin(request, principal)
        return principal

    @router.get("/me/telemetry-consent", response_model=BrowserConsentView)
    async def read_consent(caller: CallerPrincipal = Depends(authenticated)) -> BrowserConsentView:
        async with app.db.transaction() as tx:
            enabled = await admission.consent(tx, caller)
        return BrowserConsentView(enabled=enabled)

    @router.put("/me/telemetry-consent", response_model=BrowserConsentView)
    async def change_consent(
        body: BrowserConsentRequest,
        caller: CallerPrincipal = Depends(authenticated),
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> BrowserConsentView:
        async def command(tx: AsyncSession) -> CommandOutcome:
            changed = await admission.change_consent(tx, caller, enabled=body.enabled)
            return CommandOutcome(200, {"enabled": changed})

        async def reauthorize(tx: AsyncSession) -> None:
            await app.current_user(tx, caller, lock=True)

        result = await commands.execute(
            actor_scope=str(caller.user_id),
            project_scope="browser-telemetry-consent",
            operation="identity.browser_telemetry_consent",
            key=key,
            payload=body.model_dump(mode="python"),
            command=command,
            reauthorize=reauthorize,
        )
        return BrowserConsentView.model_validate(result.body)

    @router.post(
        "/telemetry/browser",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=BrowserTelemetryReceipt,
    )
    async def ingest_browser(
        request: Request,
        caller: CallerPrincipal = Depends(authenticated),
    ) -> BrowserTelemetryReceipt:
        if origin is None or exporter is None or not exporter.enabled:
            raise AccessDenied("verified browser telemetry relay is not enabled")
        content, count = await _read_bounded_json(request)
        batch = BrowserTelemetryBatch.model_validate_json(content)
        selected_project = (
            PlatformProjectId(batch.project_id) if batch.project_id is not None else None
        )
        async with app.db.transaction() as tx:
            await admission.reserve(
                tx,
                caller,
                project_id=selected_project,
                event_count=len(batch.events),
                payload_bytes=count,
            )
        # External OTLP queue is outside SQL locks; "queued" never means a
        # collector-durable acknowledgement. Only enum values are logged,
        # not raw exception, URL, token, User UUID or file path.
        events: list[object] = [
            {
                "name": f"briareus.ui.{event.kind}",
                "level": "info",
                "attributes": {
                    "component": event.component,
                    "outcome": event.outcome,
                    "route_key": event.route_key,
                    "duration_ms": event.duration_ms,
                },
            }
            for event in batch.events
        ]
        receipt = exporter.enqueue(events)
        if receipt.get("accepted") != len(events):
            raise HTTPException(status_code=503, detail="browser telemetry enqueue unavailable")
        return BrowserTelemetryReceipt(accepted_events=len(events))

    return router
