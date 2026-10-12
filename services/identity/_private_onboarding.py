# ruff: noqa: B008  # FastAPI typed Header dependencies require descriptor defaults
"""Private invitation registration and kernel-attested first-admin code delivery.

No public bootstrap route, env-sourced operator UID, user-created superuser or
uninvited self-registration. The one-time system invitation is created by the
existing Identity SQL bootstrap transaction only after SO_PEERCRED verification
of an operator socket. Registration consumes only a real hashed owner invite.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from common.platform_errors import AccessDenied, Conflict, InvalidInput, InvalidInvitation
from identity._operator_channel import UnixFirstAdminOperatorGate
from identity._service import IdentityService
from identity.private_login_source import (
    IdentitySourceUnavailable,
    TrustedIdentityLoginAdmissionPort,
    VerifiedIdentityLoginAdmission,
)

_MAX_OPERATOR_FRAME = 256


class IdentityRegistrationOutcomeUnknown(RuntimeError):
    """Registration may have committed; do NOT replay one-use invitation."""


@dataclass(frozen=True, slots=True)
class RegisteredIdentityUser:
    user_id: UUID
    role: str


class IdentityPrivateInvitationRegistration:
    """No new SQL authority; use accepted transactional IdentityService.register."""

    def __init__(
        self,
        *,
        identity: IdentityService,
        ingress: TrustedIdentityLoginAdmissionPort,
    ) -> None:
        if identity.database.engine.url.database != "briareus_identity" or ingress is None:
            raise ValueError("Identity invitation registration requires own DB and real C2")
        self.identity = identity
        self.ingress = ingress

    async def register(
        self,
        *,
        evidence: object,
        invitation: SecretStr,
        username: str,
        password: SecretStr,
    ) -> RegisteredIdentityUser:
        try:
            async with asyncio.timeout(10):
                admission = await self.ingress.require_browser_and_peer(evidence=evidence)
                if not isinstance(admission, VerifiedIdentityLoginAdmission):
                    raise IdentitySourceUnavailable("verified registration ingress missing")
                # IdentityService first probes SHA digest then locks bootstrap
                # parent row before consuming invite: no second first admin.
                user = await self.identity.register(
                    invitation=invitation.get_secret_value(),
                    username=username,
                    password=password.get_secret_value(),
                )
                return RegisteredIdentityUser(user_id=user.id, role=user.role.value)
        except (InvalidInvitation, InvalidInput, Conflict):
            raise
        except Exception:
            # Unknown DB/C2 failure is NOT a known-invalid invite, and may
            # follow a committed registration. Never retry automatically.
            raise IdentityRegistrationOutcomeUnknown(
                "Identity registration outcome unknown"
            ) from None


class PrivateInvitationRegistrationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    invitation: SecretStr = Field(min_length=32, max_length=256)
    username: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=12, max_length=4096)

    @field_validator("invitation")
    @classmethod
    def canonical_invitation(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw.isascii() or not all(x.isalnum() or x in "_-" for x in raw):
            raise ValueError("invitation format invalid")
        return value


class PrivateInvitationRegistrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    user_id: UUID
    role: str


def build_unmounted_invitation_registration_router(
    registration: IdentityPrivateInvitationRegistration,
) -> APIRouter:
    if not isinstance(registration, IdentityPrivateInvitationRegistration):
        raise ValueError("trusted Identity invitation source required")
    router = APIRouter(prefix="/internal/v1/identity", tags=["identity-invitation-private"])

    @router.post("/register", response_model=PrivateInvitationRegistrationResult, status_code=201)
    async def redeem(
        request: Request,
        response: Response,
        payload: PrivateInvitationRegistrationPayload,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=36, max_length=36),
    ) -> PrivateInvitationRegistrationResult:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        if operation_uuid.version != 4 or idempotency_key != str(operation_uuid):
            raise HTTPException(422, detail="original registration key mismatch")
        if request.headers.get("cookie") is not None:
            raise HTTPException(401, detail="authenticated registration C2 required")
        try:
            result = await registration.register(
                evidence=request,
                invitation=payload.invitation,
                username=payload.username,
                password=payload.password,
            )
        except (InvalidInvitation, InvalidInput, Conflict):
            # Do not distinguish an expired/used/missing system invitation
            # or expose existing usernames over an unverified bootstrap.
            raise HTTPException(403, detail="invitation registration rejected") from None
        except IdentityRegistrationOutcomeUnknown:
            # The owner transaction may have committed before transport
            # failure. A new UUID/code attempt is NEVER safe replay.
            raise
        except IdentitySourceUnavailable:
            raise IdentityRegistrationOutcomeUnknown(
                "Identity registration authority unavailable"
            ) from None
        # Completing registration NEVER automatically signs a user in; login
        # requires a separate current TLS/peer + password/JTI admission.
        return PrivateInvitationRegistrationResult(
            user_id=result.user_id,
            role=result.role,
        )

    return router


class RestrictedFirstAdminCodeDelivery:
    """One operator-only AF_UNIX accepted stream; no stdout/env/HTTP secret."""

    def __init__(
        self,
        *,
        identity: IdentityService,
        operator_gate: UnixFirstAdminOperatorGate,
    ) -> None:
        if identity.database.engine.url.database != "briareus_identity" or not isinstance(
            operator_gate, UnixFirstAdminOperatorGate
        ):
            raise ValueError("first-admin setup requires scoped DB and approved kernel gate")
        self.identity = identity
        self.operator_gate = operator_gate

    async def issue_and_deliver(self, accepted_socket: socket.socket) -> None:
        """One length-prefixed token on a SAME connected SO_PEERCRED Unix stream.

        The trusted supervisor is the sole socket creator/listener and owns
        dedicated non-root UID/GID/ACL. No fallback operator secret or route.
        A failed write is UNKNOWN delivery; separately attested operator may
        reissue, revoking the prior unused code before the first User exists.
        """
        try:
            self.operator_gate.verify_accepted_peer(accepted_socket)
            code = await self.identity.issue_first_admin_setup(accepted_socket)
            encoded = code.get_secret_value().encode("ascii")
            if not 32 <= len(encoded) <= _MAX_OPERATOR_FRAME:
                raise IdentitySourceUnavailable("first-admin code delivery size invalid")
            frame = len(encoded).to_bytes(2, "big") + encoded
            accepted_socket.setblocking(False)
            await asyncio.wait_for(
                asyncio.get_running_loop().sock_sendall(accepted_socket, frame),
                timeout=3,
            )
        except (TimeoutError, OSError):
            raise IdentitySourceUnavailable("initial operator delivery outcome unknown") from None
        finally:
            accepted_socket.close()


class RestrictedFirstAdminOperatorListener:
    """Accept only kernel-verified operator peers on a pre-provisioned AF_UNIX listener.

    The process never creates a listening socket or selects a UID/ACL from HTTP,
    headers or an ENV override. An infrastructure-owned supervisor supplies
    an already bound, permission-restricted listener. A valid delivery is
    at-most-once; uncertain delivery never silently reissues an invitation.
    """

    def __init__(self, delivery: RestrictedFirstAdminCodeDelivery) -> None:
        if not isinstance(delivery, RestrictedFirstAdminCodeDelivery):
            raise ValueError("operator setup requires accepted Identity owner delivery")
        self.delivery = delivery

    async def deliver_once(self, listener: socket.socket) -> None:
        if (
            not isinstance(listener, socket.socket)
            or listener.family != socket.AF_UNIX
            or listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM
            or listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1
        ):
            raise IdentitySourceUnavailable("restricted operator listening socket unavailable")
        listener.setblocking(False)
        loop = asyncio.get_running_loop()
        # Bounded attempts. Invalid peers never receive a token; valid issuer
        # failure is UNKNOWN and must be inspected instead of automatically
        # regenerating a one-use first-admin code.
        for _ in range(8):
            try:
                # The invitation is issued only when a real operator arrives.
                # The ASGI lifespan cancels this wait on normal shutdown.
                accepted, _ = await loop.sock_accept(listener)
            except OSError:
                raise IdentitySourceUnavailable(
                    "restricted operator listener unavailable"
                ) from None
            try:
                self.delivery.operator_gate.verify_accepted_peer(accepted)
            except AccessDenied:
                accepted.close()
                continue
            await self.delivery.issue_and_deliver(accepted)
            return
        raise IdentitySourceUnavailable("restricted operator peer attestation denied")
