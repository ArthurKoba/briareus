# ruff: noqa: B008  # FastAPI Header descriptors are framework-executed defaults
"""Unmounted Identity-owned login and current JWT issue/verification boundary.

No Admin API, Authorization, Control or Gateway may connect directly to
Identity's PostgreSQL. Only a source-authenticated internal TLS/Unix peer,
verified browser origin and a release-pinned issuer may issue a User bearer.
No cookie/username-header fallback, fake token or password in event logs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from common.owner_contracts import VerifiedOwnerServicePeer
from common.owner_runtime import OwnerIngressVerifier, create_owner_app
from common.platform_db import OwnerDatabaseSettings
from common.platform_errors import AuthenticationRateLimited, AuthenticationRequired
from identity._domain import User
from identity._owner_ledger import OwnerCommandRow
from identity._private_current_user import (
    IdentityCurrentUserSource,
    build_unmounted_identity_current_router,
)
from identity._service import IdentityService

if TYPE_CHECKING:
    from identity._private_onboarding import (
        IdentityPrivateInvitationRegistration,
        RestrictedFirstAdminCodeDelivery,
    )

_MAX_TTL = timedelta(minutes=15)


class IdentitySourceUnavailable(RuntimeError):
    """Original password/session source unavailable; never infer invalid credentials."""


@dataclass(frozen=True, slots=True)
class VerifiedIdentityLoginAdmission:
    """Produced by the physical C2 edge, NOT by Host/Origin/Forwarded strings."""

    recipient: VerifiedOwnerServicePeer
    browser_origin: str
    source_fingerprint: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.recipient, VerifiedOwnerServicePeer)
            or self.recipient.audience != "briareus:identity"
            or self.browser_origin != "https://briareus.koba-nexus.ru"
            or len(self.source_fingerprint) != 64
            or any(x not in "0123456789abcdef" for x in self.source_fingerprint)
            or self.expires_at.tzinfo is None
            or not datetime.now(UTC) < self.expires_at <= self.recipient.expires_at
        ):
            raise ValueError("Identity login requires genuine browser and C2 source")


class TrustedIdentityLoginAdmissionPort(Protocol):
    async def require_browser_and_peer(self, *, evidence: object) -> VerifiedIdentityLoginAdmission:
        """Verify real TLS Host/Origin and registered mTLS/Unix service peer.

        Produce a stable non-reversible rate-limit source fingerprint from
        verified connection data, not a user-controlled X-Forwarded-For.
        """
        ...


class IssuedIdentityBearer(BaseModel):
    """Return only a real issuer-signed, pinned, short-lived User session."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    token: SecretStr
    subject_user_id: UUID
    jti: UUID
    credential_version: int = Field(ge=1)
    issuer: str = Field(min_length=1, max_length=160)
    audience: str = Field(min_length=1, max_length=160)
    issued_at: datetime
    expires_at: datetime

    def require_current_shape(self, user: User, *, issuer: str, audience: str) -> None:
        now = datetime.now(UTC)
        if (
            self.subject_user_id != user.id
            or self.subject_user_id.version != 4
            or self.jti.version != 4
            or self.credential_version != user.credential_version
            or self.issuer != issuer
            or self.audience != audience
            or self.issued_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or not self.issued_at <= now < self.expires_at
            or self.expires_at - self.issued_at > _MAX_TTL
            or not 40 <= len(self.token.get_secret_value()) <= 8192
        ):
            raise AuthenticationRequired("source-signed Identity login claims unavailable")


class TrustedIdentitySessionIssuer(Protocol):
    async def issue_for_current_user(
        self, *, user: User, admission: VerifiedIdentityLoginAdmission
    ) -> IssuedIdentityBearer:
        """Pin issuer/audience and reserve JTI in actual Identity owner DB.

        Recheck current User enabled/deleted and credential version before
        issuing, not merely trust a stale password verification result.
        """
        ...

    async def require_current(
        self,
        *,
        issued: IssuedIdentityBearer,
        admission: VerifiedIdentityLoginAdmission,
    ) -> None:
        """Cryptographically verify token and reread current User+JTI denylist."""
        ...

    async def revoke_user_token(
        self, *, bearer: SecretStr, admission: VerifiedIdentityLoginAdmission
    ) -> None:
        """Revoke one valid signed JTI in Identity owner SQL, never in Gateway."""
        ...


class IdentityPrivateLoginSource:
    """Ready-to-inject real Identity password admission, never a public route."""

    def __init__(
        self,
        *,
        identity: IdentityService,
        ingress: TrustedIdentityLoginAdmissionPort,
        tokens: TrustedIdentitySessionIssuer,
        pinned_issuer: str,
        pinned_audience: str,
        login_pepper: bytes,
    ) -> None:
        if not all((identity, ingress, tokens, pinned_issuer, pinned_audience)):
            raise ValueError("Identity private login requires genuine owner/C2/session issuer")
        if len(login_pepper) < 32:
            raise ValueError("independent private Identity login rate-limit key required")
        self.identity_login_pepper = login_pepper
        if identity.database.engine.url.database != "briareus_identity":
            raise ValueError("Identity login must own only the Identity logical DB")
        self.identity = identity
        self.ingress = ingress
        self.tokens = tokens
        self.issuer = pinned_issuer
        self.audience = pinned_audience

    async def _reserve_original_login(
        self,
        *,
        original_uuid: UUID,
        username: str,
        password: SecretStr,
        admission: VerifiedIdentityLoginAdmission,
    ) -> UUID:
        """Durably consume one original pre-auth operation before issuing a JTI.

        An ambiguous response must never mint another bearer for the same
        original operation. Existing Identity commands migration owns this
        table, and no secret or reversible password fingerprint is persisted.
        """
        if original_uuid.version != 4:
            raise AuthenticationRequired("canonical original login UUID required")
        digest = hmac.new(
            self.identity_login_pepper,
            b"identity-login-v1\0"
            + username.encode("utf-8")
            + b"\0"
            + password.get_secret_value().encode("utf-8")
            + b"\0"
            + admission.source_fingerprint.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        receipt_id = uuid4()
        now = datetime.now(UTC)
        statement = (
            insert(OwnerCommandRow)
            .values(
                id=receipt_id,
                operation_uuid=original_uuid,
                actor_scope="identity:preauth",
                project_scope="none",
                operation="identity.login",
                key=str(original_uuid),
                fingerprint=digest,
                expected_owner_revision="identity-login-v1",
                state="pending",
                encrypted_outcome=None,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=1),
            )
            .on_conflict_do_nothing()
            .returning(OwnerCommandRow.id)
        )
        async with self.identity.database.transaction() as tx:
            if await tx.scalar(statement) is None:
                raise IdentitySourceUnavailable(
                    "original Identity login already consumed; outcome may be unknown"
                )
        return receipt_id

    async def _complete_original_login(self, receipt_id: UUID) -> None:
        async with self.identity.database.transaction() as tx:
            result = await tx.execute(
                update(OwnerCommandRow)
                .where(OwnerCommandRow.id == receipt_id, OwnerCommandRow.state == "pending")
                .values(state="completed", updated_at=datetime.now(UTC))
                .returning(OwnerCommandRow.id)
            )
            if result.scalar_one_or_none() != receipt_id:
                raise IdentitySourceUnavailable("original Identity login status unavailable")

    async def login(
        self,
        *,
        evidence: object,
        username: str,
        password: SecretStr,
        original_uuid: UUID,
    ) -> IssuedIdentityBearer:
        if not 3 <= len(username) <= 128 or not 12 <= len(password.get_secret_value()) <= 4096:
            raise AuthenticationRequired("valid Identity login required")
        try:
            async with asyncio.timeout(5):
                admission = await self.ingress.require_browser_and_peer(evidence=evidence)
                if not isinstance(admission, VerifiedIdentityLoginAdmission):
                    raise AuthenticationRequired("Identity login source is not authenticated")
                user = await self.identity.authenticate_limited(
                    username,
                    password.get_secret_value(),
                    source=admission.source_fingerprint,
                    pepper=self.identity_login_pepper,
                )
                if user is None or not user.enabled:
                    raise AuthenticationRequired("invalid Identity credentials")
                receipt_id = await self._reserve_original_login(
                    original_uuid=original_uuid,
                    username=username,
                    password=password,
                    admission=admission,
                )
                issued = await self.tokens.issue_for_current_user(user=user, admission=admission)
                issued.require_current_shape(user, issuer=self.issuer, audience=self.audience)
                await self.tokens.require_current(issued=issued, admission=admission)
                await self._complete_original_login(receipt_id)
                return issued
        except (AuthenticationRequired, AuthenticationRateLimited):
            raise
        except Exception:
            raise IdentitySourceUnavailable("current Identity login source unavailable") from None

    async def logout(self, *, evidence: object, bearer: SecretStr) -> None:
        if not 40 <= len(bearer.get_secret_value()) <= 8192:
            raise AuthenticationRequired("current Identity bearer required")
        try:
            async with asyncio.timeout(5):
                admission = await self.ingress.require_browser_and_peer(evidence=evidence)
                if not isinstance(admission, VerifiedIdentityLoginAdmission):
                    raise AuthenticationRequired("verified Identity logout peer required")
                await self.tokens.revoke_user_token(bearer=bearer, admission=admission)
        except AuthenticationRequired:
            raise
        except Exception:
            raise IdentitySourceUnavailable("Identity logout source unavailable") from None


class PrivateIdentityLoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=12, max_length=4096)


class PrivateIdentityLoginResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime


def build_unmounted_private_identity_login_router(
    login: IdentityPrivateLoginSource,
) -> APIRouter:
    """Private Identity service ONLY; no global API SQL or cookie fallback."""
    if not isinstance(login, IdentityPrivateLoginSource):
        raise ValueError("unverified Identity issuer cannot mount even privately")
    router = APIRouter(prefix="/internal/v1/identity", tags=["identity-private-login"])

    @router.post("/login", response_model=PrivateIdentityLoginResult)
    async def login_user(
        request: Request,
        response: Response,
        body: PrivateIdentityLoginPayload,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=36, max_length=36),
    ) -> PrivateIdentityLoginResult:
        if operation_uuid.version != 4 or idempotency_key != str(operation_uuid):
            raise HTTPException(422, detail="original Identity login key mismatch")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        if request.headers.get("cookie") is not None:
            raise HTTPException(
                401,
                detail="bearer-only Identity login requires verified C2",
                headers={"Cache-Control": "no-store"},
            )
        try:
            issued = await login.login(
                evidence=request,
                username=body.username,
                password=body.password,
                original_uuid=operation_uuid,
            )
        except AuthenticationRateLimited:
            raise HTTPException(
                429,
                detail="Identity login rate limit active",
                headers={"Cache-Control": "no-store"},
            ) from None
        except IdentitySourceUnavailable:
            raise HTTPException(
                503,
                detail="current Identity issuer unavailable",
                headers={"Cache-Control": "no-store"},
            ) from None
        except AuthenticationRequired:
            raise HTTPException(
                401,
                detail="invalid Identity credential",
                headers={"Cache-Control": "no-store"},
            ) from None
        # Expose ONLY the properly issued User bearer through a verified,
        # private HTTPS-forwarded response. Never serialize SecretStr blindly.
        return PrivateIdentityLoginResult(
            access_token=issued.token.get_secret_value(),
            expires_at=issued.expires_at,
        )

    @router.post("/logout", status_code=204)
    async def logout_user(
        request: Request,
        response: Response,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=36, max_length=36),
    ) -> None:
        if operation_uuid.version != 4 or idempotency_key != str(operation_uuid):
            raise HTTPException(422, detail="original Identity logout key mismatch")
        response.headers["Cache-Control"] = "no-store"
        if request.headers.get("cookie") is not None:
            raise HTTPException(
                401,
                detail="bearer-only Identity logout",
                headers={"Cache-Control": "no-store"},
            )
        bearer = request.headers.get("authorization", "")
        if not bearer.startswith("Bearer ") or bearer.count(" ") != 1:
            raise HTTPException(401, detail="current Identity bearer required")
        try:
            await login.logout(evidence=request, bearer=SecretStr(bearer[7:]))
        except IdentitySourceUnavailable:
            raise HTTPException(
                503,
                detail="Identity revocation source unavailable",
                headers={"Cache-Control": "no-store"},
            ) from None
        except AuthenticationRequired:
            raise HTTPException(
                401,
                detail="current Identity credential rejected",
                headers={"Cache-Control": "no-store"},
            ) from None

    return router


def create_unmounted_identity_private_app(
    login: IdentityPrivateLoginSource,
    *,
    db_settings: OwnerDatabaseSettings,
    trusted_ingress: OwnerIngressVerifier,
    current_users: IdentityCurrentUserSource,
    registration: IdentityPrivateInvitationRegistration,
    operator_delivery: RestrictedFirstAdminCodeDelivery | None = None,
    operator_listener: socket.socket | None = None,
) -> FastAPI:
    """SOURCE-only private Identity composition; default published app unchanged.

    Own Identity PostgreSQL schema migrates/verifies before any route accepts
    an actual call. The same reviewed URL/role must back source login and
    owner Alembic. Identity login issuer connection is closed at shutdown.
    """
    from identity._private_onboarding import (
        IdentityPrivateInvitationRegistration,
        IdentityRegistrationOutcomeUnknown,
        RestrictedFirstAdminCodeDelivery,
        RestrictedFirstAdminOperatorListener,
        build_unmounted_invitation_registration_router,
    )
    from identity._private_user_session import IdentityPrivateUserSessionIssuer

    if (
        not isinstance(login, IdentityPrivateLoginSource)
        or not isinstance(registration, IdentityPrivateInvitationRegistration)
        or db_settings.owner != "identity"
        or trusted_ingress is None
        or not isinstance(current_users, IdentityCurrentUserSource)
        or login.identity.database.engine.url != db_settings.url
        or current_users.db.engine.url != db_settings.url
        or registration.identity.database.engine.url != db_settings.url
        or registration.identity is not login.identity
        or not isinstance(login.tokens, IdentityPrivateUserSessionIssuer)
        or not login.tokens.matches_accepted_identity_source(
            database=login.identity.database,
            public_key=current_users.key,
            issuer=login.issuer,
            audience=login.audience,
        )
        or current_users.issuer != login.issuer
        or current_users.audience != login.audience
    ):
        raise ValueError("Identity private login/owner migrations must share reviewed DB")
    if (operator_delivery is None) != (operator_listener is None):
        raise ValueError("operator socket and approved kernel gate must be provided together")
    if operator_delivery is not None and (
        not isinstance(operator_delivery, RestrictedFirstAdminCodeDelivery)
        or operator_delivery.identity is not login.identity
        or not isinstance(operator_listener, socket.socket)
        or operator_listener.family != socket.AF_UNIX
        or operator_listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM
        or operator_listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1
    ):
        raise ValueError("first admin operator listener must share the current Identity owner")
    operator_supervisor = (
        RestrictedFirstAdminOperatorListener(operator_delivery)
        if operator_delivery is not None
        else None
    )
    app = create_owner_app("identity", settings=db_settings, trusted_ingress=trusted_ingress)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def private_lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            async with original_lifespan(application):
                # Only a real supervisor-owned listening socket can activate
                # first-admin code delivery. No public HTTP/ENV bootstrap path.
                if operator_supervisor is None or operator_listener is None:
                    yield
                else:
                    task = asyncio.create_task(operator_supervisor.deliver_once(operator_listener))
                    try:
                        yield
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
        finally:
            await login.identity.database.close()

    app.router.lifespan_context = private_lifespan
    app.include_router(build_unmounted_private_identity_login_router(login))
    app.include_router(build_unmounted_invitation_registration_router(registration))
    app.include_router(build_unmounted_identity_current_router(current_users))

    @app.exception_handler(IdentityRegistrationOutcomeUnknown)
    async def registration_uncertain(
        _request: Request, _error: IdentityRegistrationOutcomeUnknown
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "OWNER_SOURCE_UNAVAILABLE",
                    "originalOutcomeUnknown": True,
                }
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @app.exception_handler(HTTPException)
    async def private_http_failure(_request: Request, error: HTTPException) -> JSONResponse:
        # Never echo exception.detail or submitted User credentials. Only
        # allowed private BFF envelope codes cross the trusted Gateway.
        code = (
            "AUTHENTICATION_REQUIRED"
            if error.status_code == 401
            else "AUTHENTICATION_RATE_LIMITED"
            if error.status_code == 429
            else "INVITATION_REJECTED"
            if error.status_code == 403
            else "INVALID_INPUT"
            if error.status_code == 422
            else "OWNER_SOURCE_UNAVAILABLE"
        )
        status = error.status_code if error.status_code in {401, 403, 422, 429} else 503
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "originalOutcomeUnknown": False}},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @app.exception_handler(RequestValidationError)
    async def private_input_rejected(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        # Never echo the submitted password/SecretStr or invalid token in a
        # Pydantic 422 validation body, even over the private ingress.
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "INVALID_INPUT", "originalOutcomeUnknown": False}},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    return app
