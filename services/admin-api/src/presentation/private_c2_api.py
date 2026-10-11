# ruff: noqa: B008  # FastAPI Header descriptors are framework-executed defaults
"""SOURCE-ONLY private Admin API bound to approved C2, never the public shell.

The Gateway's browser bearer must be independently verified against Identity,
revocation/JTI and expiry before this API may read source-owner evidence.
Both an authenticated browser and a separately attested TLS/Unix service peer
are mandatory. No guessed URL, header-derived peer or cross-owner SQL session.
The published platform_runtime.app intentionally does NOT mount this router.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, SecretStr

from common.owner_bff_models import (
    OwnerPage,
    OwnerProjectView,
    OwnerTeamView,
    VerifiedAdminCaller,
)
from common.owner_bff_signed import canonical_original_identity
from common.owner_contracts import OwnerAuthorityUnavailable, VerifiedOwnerServicePeer
from common.private_user_token import (
    IdentityCredentialRejected,
    PrivateUserTokenClaims,
    require_pinned_current_user_token,
)

from .owner_bff_evidence import (
    BffEffectEvidence,
    BffOwnerEvidence,
    BffScope,
    OwnerBffEvidenceSource,
)
from .owner_bff_private_handlers import (
    PrivateBffOriginalInspect,
    PrivateBffRead,
    TrustedBffAdmissionError,
)
from .private_c2_views import (
    PrivateAgentSessionPage,
    TrustedCurrentAccessSessionsPort,
    TrustedCurrentOwnerPagesPort,
)

_PRIVATE_PREFIX = "/internal/v1/platform"
_C2_HOST = "briareus.koba-nexus.ru"


@dataclass(frozen=True, slots=True)
class VerifiedPrivateC2Connection:
    """Result of trusted socket/proxy verification, never from HTTP headers."""

    service_peer: VerifiedOwnerServicePeer
    public_host: str
    public_origin: str
    verified_scheme: Literal["https"]
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.service_peer, VerifiedOwnerServicePeer)
            or self.service_peer.audience != "briareus:admin-api"
            or self.public_host != _C2_HOST
            or self.public_origin != f"https://{_C2_HOST}"
            or self.verified_scheme != "https"
            or self.expires_at.tzinfo is None
            or self.expires_at <= datetime.now(UTC)
            or self.expires_at > self.service_peer.expires_at
        ):
            raise ValueError("private Admin API upstream TLS/recipient not attested")


@dataclass(frozen=True, slots=True)
class VerifiedPrivateHuman:
    """Independent Identity-source verified bearer, including CURRENT JTI."""

    caller: VerifiedAdminCaller
    jti: UUID
    bearer_expires_at: datetime
    issuer: str
    audience: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.caller, VerifiedAdminCaller)
            or self.caller.source != "verified-admin-bearer"
            or self.caller.user_id.version != 4
            or self.jti.version != 4
            or self.bearer_expires_at.tzinfo is None
            or self.bearer_expires_at <= datetime.now(UTC)
            or not self.issuer
            or not self.audience
            or len(self.issuer) > 160
            or len(self.audience) > 160
        ):
            raise ValueError("current Identity bearer/JTI evidence invalid")


class TrustedPrivateC2ConnectionPort(Protocol):
    async def verify(self, *, request: Request) -> VerifiedPrivateC2Connection:
        """Verify actual trusted TLS terminator, Host/Origin and mTLS/Unix peer.

        Ignore caller Forwarded/X-Forwarded-* identity assertions unless a
        separately trusted edge has authenticated, stripped and reissued them.
        """


class TrustedIdentityBearerPort(Protocol):
    async def verify_current(
        self,
        *,
        bearer: SecretStr,
        connection: VerifiedPrivateC2Connection,
    ) -> VerifiedPrivateHuman:
        """Pin current Identity issuer/audience/credential revision and JTI.

        Must recheck enabled/non-deleted User + token JTI nonrevocation, not
        trust a JWT's signature, cookie or prior frontend state by itself.
        """


class TrustedIdentityCurrentStatusPort(Protocol):
    async def require_current(
        self,
        *,
        bearer: SecretStr,
        claims: PrivateUserTokenClaims,
        recipient: VerifiedOwnerServicePeer,
    ) -> VerifiedAdminCaller:
        """REVERIFY signed bearer and current enabled User/JTI in Identity DB.

        Claims alone are untrusted; Identity must check the original signed
        token against its release pin, plus registered private C2 peer.
        Gateway/Admin may never open an Identity SQL session.
        """


class PinnedIdentityBearerVerifier:
    """Concrete Ed25519 verifier; never accepts a key from request/JWKS."""

    def __init__(
        self,
        *,
        public_key: Ed25519PublicKey,
        issuer: str,
        audience: str,
        identity: TrustedIdentityCurrentStatusPort,
    ) -> None:
        if (
            not isinstance(public_key, Ed25519PublicKey)
            or not issuer
            or not audience
            or identity is None
        ):
            raise ValueError("private Admin Identity release key/source unavailable")
        self.key = public_key
        self.issuer = issuer
        self.audience = audience
        self.identity = identity

    async def verify_current(
        self, *, bearer: SecretStr, connection: VerifiedPrivateC2Connection
    ) -> VerifiedPrivateHuman:
        try:
            claims = require_pinned_current_user_token(
                bearer.get_secret_value(),
                pinned_public_key=self.key,
                trusted_issuer=self.issuer,
                trusted_audience=self.audience,
            )
        except OwnerAuthorityUnavailable:
            raise TrustedBffAdmissionError("authentication") from None
        try:
            async with asyncio.timeout(3):
                actor = await self.identity.require_current(
                    bearer=bearer, claims=claims, recipient=connection.service_peer
                )
        except IdentityCredentialRejected:
            # Only a truly authenticated private Identity source may prove
            # revoked/disabled User. Network or DB outage remains UNKNOWN/503.
            raise TrustedBffAdmissionError("authentication") from None
        if (
            not isinstance(actor, VerifiedAdminCaller)
            or actor.user_id != claims.sub
            or actor.credential_version != claims.credential_version
        ):
            raise RuntimeError("fresh Identity User/JTI source mismatch")
        return VerifiedPrivateHuman(
            caller=actor,
            jti=claims.jti,
            bearer_expires_at=datetime.fromtimestamp(claims.exp, UTC),
            issuer=claims.iss,
            audience=claims.aud,
        )


class TrustedOwnerScopePort(Protocol):
    async def require_current(
        self,
        *,
        actor: VerifiedPrivateHuman,
        connection: VerifiedPrivateC2Connection,
        scope: BffScope,
        purpose: Literal["read", "original_inspect"],
        operation: str | None,
        agent_session_uuid: UUID | None,
    ) -> None:
        """Fresh Identity+Control+Access right for exact Team/Project action.

        For original Project effects, check ACTIVE AgentSession and hard TTL,
        delegated scope, grant revision and original operation policy. A Team
        global operation must NOT invent a Project/Session UUID.
        """


class PrivateC2BoundAdmission:
    """Request-scoped C2 adapter with explicit one-call scope verification."""

    def __init__(
        self,
        *,
        transport: TrustedPrivateC2ConnectionPort,
        identity: TrustedIdentityBearerPort,
        scopes: TrustedOwnerScopePort,
        pinned_identity_issuer: str,
        pinned_bearer_audience: str,
        recipient_service_id: UUID,
        recipient_instance_uuid: UUID,
    ) -> None:
        if not all((transport, identity, scopes)) or not all(
            (pinned_identity_issuer, pinned_bearer_audience)
        ):
            raise ValueError("verified source ports mandatory")
        if recipient_service_id.version != 4 or recipient_instance_uuid.version != 4:
            raise ValueError("pinned recipient UUIDv4 required")
        self.transport = transport
        self.identity = identity
        self.scopes = scopes
        self.issuer = pinned_identity_issuer
        self.audience = pinned_bearer_audience
        self.recipient_id = recipient_service_id
        self.recipient_instance = recipient_instance_uuid

    async def admit_verified_request(
        self,
        *,
        request: Request,
        scope: BffScope,
        purpose: Literal["read", "original_inspect"],
        operation: str | None = None,
        agent_session_uuid: UUID | None = None,
    ) -> VerifiedAdminCaller:
        authorization = request.headers.get("authorization", "")
        if (
            not authorization.startswith("Bearer ")
            or authorization.count(" ") != 1
            or request.headers.get("cookie") is not None
            or not 40 <= len(authorization[7:]) <= 8192
        ):
            raise TrustedBffAdmissionError("authentication")
        try:
            async with asyncio.timeout(3):
                c2 = await self.transport.verify(request=request)
                if (
                    not isinstance(c2, VerifiedPrivateC2Connection)
                    or c2.service_peer.service_id != self.recipient_id
                    or c2.service_peer.instance_uuid != self.recipient_instance
                ):
                    raise TrustedBffAdmissionError("authentication")
                current = await self.identity.verify_current(
                    bearer=SecretStr(authorization[7:]), connection=c2
                )
                if (
                    not isinstance(current, VerifiedPrivateHuman)
                    or current.issuer != self.issuer
                    or current.audience != self.audience
                ):
                    raise TrustedBffAdmissionError("authentication")
                # A caller without a current authenticated User is always
                # rejected as 401 before checking Project/Session selectors.
                if (
                    purpose == "original_inspect"
                    and scope.kind == "project"
                    and (agent_session_uuid is None or agent_session_uuid.version != 4)
                ):
                    raise TrustedBffAdmissionError("permission")
                await self.scopes.require_current(
                    actor=current,
                    connection=c2,
                    scope=scope,
                    purpose=purpose,
                    operation=operation,
                    agent_session_uuid=agent_session_uuid,
                )
                if current.bearer_expires_at <= datetime.now(UTC) or c2.expires_at <= datetime.now(
                    UTC
                ):
                    raise RuntimeError("C2 or User bearer expired during scope lookup")
                return current.caller
        except TrustedBffAdmissionError:
            raise
        except Exception:
            raise RuntimeError("independent C2/owner source unavailable") from None


class PrivateC2SafeError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    code: Literal[
        "AUTHENTICATION_REQUIRED", "SCOPE_DENIED", "OWNER_SOURCE_UNAVAILABLE", "INVALID_INPUT"
    ]
    originalOutcomeUnknown: bool


class PrivateC2ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    error: PrivateC2SafeError


class PrivateC2HttpError(Exception):
    def __init__(
        self,
        *,
        status_code: Literal[401, 403, 422, 503],
        code: Literal[
            "AUTHENTICATION_REQUIRED",
            "SCOPE_DENIED",
            "OWNER_SOURCE_UNAVAILABLE",
            "INVALID_INPUT",
        ],
        original_outcome_unknown: bool,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.original_outcome_unknown = original_outcome_unknown
        super().__init__(code)


class PrivateOwnerApiPorts(Protocol):
    bff_source: OwnerBffEvidenceSource
    c2: PrivateC2BoundAdmission
    pages: TrustedCurrentOwnerPagesPort
    sessions: TrustedCurrentAccessSessionsPort

    async def attest_started(self) -> None:
        """Actual private C2 release/peer/owner source registration, no HTTP header fallback."""

    async def require_ready(self) -> None:
        """Read-only check approved C2 peers, pinned Identity and owner sources.

        Never infer ready from a TCP port, /health/live or container state.
        """

    async def close(self) -> None:
        """Close private owner network clients; NEVER mutate foreign DB."""


def private_api_router(ports: PrivateOwnerApiPorts) -> APIRouter:
    """Private, bearer-only typed read/original inspect; never auto-mounted."""
    if (
        ports is None
        or ports.c2 is None
        or ports.bff_source is None
        or ports.pages is None
        or ports.sessions is None
    ):
        raise ValueError("C2/BFF scoped source ports missing")
    router = APIRouter(prefix=_PRIVATE_PREFIX, tags=["private-owner-source"])

    def unavailable(exc: Exception, *, original: bool) -> PrivateC2HttpError:
        if isinstance(exc, TrustedBffAdmissionError):
            if exc.reason == "authentication":
                return PrivateC2HttpError(
                    status_code=401,
                    code="AUTHENTICATION_REQUIRED",
                    original_outcome_unknown=original,
                )
            return PrivateC2HttpError(
                status_code=403,
                code="SCOPE_DENIED",
                original_outcome_unknown=original,
            )
        return PrivateC2HttpError(
            status_code=503,
            code="OWNER_SOURCE_UNAVAILABLE",
            original_outcome_unknown=original,
        )

    @router.get("/projects", response_model=OwnerPage[OwnerProjectView])
    async def projects(
        request: Request,
        response: Response,
        after_id: UUID | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> OwnerPage[OwnerProjectView]:
        response.headers["Cache-Control"] = "no-store"
        if after_id is not None and after_id.version != 4:
            raise PrivateC2HttpError(
                status_code=422, code="INVALID_INPUT", original_outcome_unknown=False
            )
        try:
            actor = await ports.c2.admit_verified_request(
                request=request, scope=BffScope(kind="account"), purpose="read"
            )
            async with asyncio.timeout(5):
                page = await ports.pages.visible_projects(actor, after_id=after_id, limit=limit)
            if not isinstance(page, OwnerPage) or len(page.items) > limit:
                raise RuntimeError("unbounded current Control Project source")
            return page
        except Exception as exc:
            raise unavailable(exc, original=False) from None

    @router.get("/teams", response_model=OwnerPage[OwnerTeamView])
    async def teams(
        request: Request,
        response: Response,
        after_id: UUID | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> OwnerPage[OwnerTeamView]:
        response.headers["Cache-Control"] = "no-store"
        if after_id is not None and after_id.version != 4:
            raise PrivateC2HttpError(
                status_code=422, code="INVALID_INPUT", original_outcome_unknown=False
            )
        try:
            actor = await ports.c2.admit_verified_request(
                request=request, scope=BffScope(kind="account"), purpose="read"
            )
            async with asyncio.timeout(5):
                page = await ports.pages.visible_teams(actor, after_id=after_id, limit=limit)
            if not isinstance(page, OwnerPage) or len(page.items) > limit:
                raise RuntimeError("unbounded current Control Team source")
            return page
        except Exception as exc:
            raise unavailable(exc, original=False) from None

    @router.get("/projects/{project_id}/sessions", response_model=PrivateAgentSessionPage)
    async def current_sessions(
        request: Request, response: Response, project_id: UUID
    ) -> PrivateAgentSessionPage:
        response.headers["Cache-Control"] = "no-store"
        if project_id.version != 4:
            raise PrivateC2HttpError(
                status_code=422, code="INVALID_INPUT", original_outcome_unknown=False
            )
        try:
            actor = await ports.c2.admit_verified_request(
                request=request,
                scope=BffScope(kind="project", projectId=project_id),
                purpose="read",
            )
            async with asyncio.timeout(5):
                page = await ports.sessions.visible_sessions(caller=actor, project_id=project_id)
            if (
                not isinstance(page, PrivateAgentSessionPage)
                or page.actorUserId != actor.user_id
                or page.projectId != project_id
            ):
                raise RuntimeError("current Access session owner source mismatch")
            return page
        except Exception as exc:
            raise unavailable(exc, original=False) from None

    @router.post("/current", response_model=BffOwnerEvidence)
    async def current(
        request: Request, response: Response, body: PrivateBffRead
    ) -> BffOwnerEvidence:
        response.headers["Cache-Control"] = "no-store"
        try:
            actor = await ports.c2.admit_verified_request(
                request=request, scope=body.scope, purpose="read"
            )
            async with asyncio.timeout(5):
                answer = await ports.bff_source.current(actor, body.scope)
            if answer.actorUserId != actor.user_id or answer.scope != body.scope:
                raise RuntimeError("owner source returned inconsistent actor/scope")
            return answer
        except Exception as exc:
            raise unavailable(exc, original=False) from None

    @router.post("/original/inspect", response_model=BffEffectEvidence)
    async def inspect_original(
        request: Request,
        response: Response,
        body: PrivateBffOriginalInspect,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        agent_session_uuid: UUID | None = Header(default=None, alias="Agent-Session-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=36, max_length=36),
    ) -> BffEffectEvidence:
        response.headers["Cache-Control"] = "no-store"
        if operation_uuid != body.operationUuid or idempotency_key != body.idempotencyKey:
            raise PrivateC2HttpError(
                status_code=422,
                code="INVALID_INPUT",
                original_outcome_unknown=True,
            )
        try:
            canonical_original_identity(operation_uuid, idempotency_key)
        except Exception:
            raise PrivateC2HttpError(
                status_code=422, code="INVALID_INPUT", original_outcome_unknown=True
            ) from None
        try:
            actor = await ports.c2.admit_verified_request(
                request=request,
                scope=body.scope,
                purpose="original_inspect",
                operation=body.binding.operation,
                agent_session_uuid=agent_session_uuid,
            )
            async with asyncio.timeout(5):
                answer = await ports.bff_source.inspect_original(
                    actor, body.scope, body.binding, idempotency_key, operation_uuid
                )
            if (
                answer.actorUserId != actor.user_id
                or answer.scope != body.scope
                or answer.operationUuid != operation_uuid
                or answer.idempotencyKey != idempotency_key
                or answer.binding != body.binding
            ):
                raise RuntimeError("inconsistent signed original owner evidence")
            return answer
        except Exception as exc:
            raise unavailable(exc, original=True) from None

    return router


def create_unmounted_private_owner_api(ports: PrivateOwnerApiPorts) -> FastAPI:
    """Source-only app composition. Production entrypoint does NOT call this."""
    if ports is None:
        raise ValueError("no accepted private C2")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            await ports.attest_started()
            yield
        finally:
            # Also close partially initialized clients if C2 startup attestation fails.
            await ports.close()

    app = FastAPI(
        title="Briareus Owner Private API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.include_router(private_api_router(ports))

    @app.exception_handler(PrivateC2HttpError)
    async def private_failure(_request: Request, exc: PrivateC2HttpError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=PrivateC2ErrorEnvelope(
                error=PrivateC2SafeError(
                    code=exc.code, originalOutcomeUnknown=exc.original_outcome_unknown
                )
            ).model_dump(mode="json"),
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @app.exception_handler(RequestValidationError)
    async def private_input_failure(request: Request, _exc: RequestValidationError) -> JSONResponse:
        # Do not echo Pydantic error input; it can contain secrets or full
        # original command bodies. Only the typed safe code is public.
        return JSONResponse(
            status_code=422,
            content=PrivateC2ErrorEnvelope(
                error=PrivateC2SafeError(
                    code="INVALID_INPUT",
                    originalOutcomeUnknown=request.url.path.endswith("/original/inspect"),
                )
            ).model_dump(mode="json"),
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @app.get("/health/live", include_in_schema=False)
    async def live() -> dict[str, str]:
        return {"state": "live", "api": "private-source", "authorization": "per-request"}

    @app.get("/health/ready", include_in_schema=False)
    async def ready() -> dict[str, str]:
        try:
            async with asyncio.timeout(3):
                await ports.require_ready()
            return {"state": "ready", "authorization": "verified-source"}
        except Exception:
            raise HTTPException(503, detail="private C2/owner source not ready") from None

    return app
