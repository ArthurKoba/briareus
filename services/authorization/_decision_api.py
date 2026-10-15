"""Private Gateway/Hand authorization boundary backed by Access SQL and Cedar.

No user IDs or permissions from request headers/body are trusted. The attestor
is injected ONLY by independently verified Rauthy + service-peer integration.
Without it, the route is mounted but unavailable and cannot grant access.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from starlette.requests import ClientDisconnect

from authorization._access_cedar import permits_current_project_grant
from authorization._resource_scope import (
    EffectResource,
    HandName,
    resource_key,
    validate_effect_scope,
    validate_project_resource_scope,
)
from authorization._session_persistence import ProjectAgentSessionRow
from common.platform_db import PlatformDatabase

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

_MAX_BYTES = 8192
_DECISION_AUTH_TIMEOUT_SECONDS = 12.0


@dataclass(frozen=True, slots=True)
class PrivateRequestBodyRejected(Exception):
    status_code: int
    reason: str


async def bounded_private_request(request: Request) -> tuple[bytes, Request]:
    """Read at most 8192 real ASGI bytes in one bounded 5s receive window.

    A client's Content-Length is never proof of what bytes were actually
    delivered. Missing/duplicated/mismatched lengths, Transfer-Encoding and
    Content-Encoding are invalid private API framing. All body data is
    discarded before any caller identity, Platform/DB, Cedar or replay IO.
    """
    headers = request.headers
    sizes = headers.getlist("content-length")
    if (
        headers.getlist("content-type") != ["application/json"]
        or headers.getlist("transfer-encoding")
        or headers.getlist("content-encoding")
        or len(sizes) != 1
        or not 1 <= len(sizes[0]) <= 4
        or not sizes[0].isascii()
        or not sizes[0].isdecimal()
    ):
        raise PrivateRequestBodyRejected(422, "ambiguous private Access request framing")
    count = int(sizes[0])
    if count > _MAX_BYTES:
        raise PrivateRequestBodyRejected(413, "private Access request too large")
    body = bytearray()
    try:
        async with asyncio.timeout(5):
            async for part in request.stream():
                if len(part) > _MAX_BYTES - len(body):
                    raise PrivateRequestBodyRejected(413, "private Access request too large")
                body.extend(part)
    except (TimeoutError, RuntimeError, ClientDisconnect):
        raise PrivateRequestBodyRejected(422, "private Access body unavailable") from None
    if not body or len(body) != count:
        raise PrivateRequestBodyRejected(422, "private Access body/length mismatch")

    raw = bytes(body)
    delivered = False

    async def replay_original_receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            # Do not fabricate a client disconnect merely because the body
            # was replayed once. A real server's receive channel remains the
            # authority for disconnects while the response is being written.
            return await request.receive()
        delivered = True
        return {"type": "http.request", "body": raw, "more_body": False}

    # The transport-authenticated resolver hashes attested_request.body().
    # An independently recreated Request avoids manipulating Starlette
    # private _body while keeping real scope-injected trusted peer facts.
    return raw, Request(request.scope, receive=replay_original_receive)


class DecisionAuthenticationRequired(Exception):
    """The calling service or its delegated Rauthy subject was not verified."""


class DecisionScopeDenied(Exception):
    """A verified caller is not authorized for this Project/AgentSession."""


class DecisionAuthorityUnavailable(Exception):
    """Verified Rauthy, peer or Project current-state authority is unavailable."""


class DecisionPermit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    allowed: Literal[True] = True


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    agent_session_uuid: UUID
    action: str = Field(min_length=1, max_length=128)
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    hand: HandName | None = None
    tool: str | None = Field(default=None, min_length=1, max_length=128)
    resource: EffectResource | None = None

    @model_validator(mode="after")
    def effect_boundary(self) -> DecisionCommand:
        if self.action == "mcp.connect":
            if any(value is not None for value in (self.hand, self.tool, self.resource)):
                raise ValueError("Gateway coarse admission cannot claim an effect resource")
        elif self.hand is None or self.tool is None or self.resource is None:
            raise ValueError("Hand effect needs exact hand/tool/resource selection")
        else:
            validate_effect_scope(self.hand, self.tool, self.action, self.resource)
            validate_project_resource_scope(
                project_uuid=self.project_uuid,
                hand=self.hand,
                tool=self.tool,
                resource=self.resource,
            )
        return self

    def effect_key(self) -> str | None:
        if self.resource is None or self.hand is None or self.tool is None:
            return None
        return resource_key(self.hand, self.tool, self.resource)

    @field_validator("project_uuid", "agent_session_uuid")
    @classmethod
    def canonical_uuid(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Project and AgentSession require UUIDv4")
        return value


@dataclass(frozen=True, slots=True)
class VerifiedDecisionCaller:
    """Result of real signed OAuth + trusted service peer + Project resolution."""

    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    consumer: Literal["gateway", "hand"]
    authority: Literal["rauthy"]
    verified_peer_audience: str
    proof_expires_at: datetime
    attested_effect_key: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizedCurrentGrant:
    """Current Access result, valid only for the original authenticated request."""

    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int
    expires_at: datetime


class TrustedDecisionAttestor(Protocol):
    async def verify(self, request: Request, command: DecisionCommand) -> object:
        """Verify bearer/peer and current Project membership; never echo claims."""
        ...


class AuthorizationDecisionReader:
    """Read live Access rows; never query another service's SQL tables."""

    def __init__(self, database: PlatformDatabase) -> None:
        if database.engine.url.database != "briareus_access":
            raise ValueError("Authorization decision reader must use its own Access database")
        self._db = database

    async def current_grant(
        self, command: DecisionCommand, caller: VerifiedDecisionCaller
    ) -> AuthorizedCurrentGrant | None:
        # Project and session must be attested independently, not supplied as
        # authority by a caller-controlled POST body or forwarded user header.
        if (
            caller.authority != "rauthy"
            or caller.consumer not in {"gateway", "hand"}
            or caller.verified_peer_audience != "briareus:access"
            or caller.actor_uuid.version != 4
            or caller.project_uuid != command.project_uuid
            or caller.agent_session_uuid != command.agent_session_uuid
            or caller.proof_expires_at.tzinfo is None
            or caller.proof_expires_at <= datetime.now(UTC)
            or (command.action == "mcp.connect" and caller.consumer != "gateway")
            or (command.action != "mcp.connect" and caller.consumer != "hand")
            or caller.attested_effect_key != command.effect_key()
        ):
            return None
        async with self._db.transaction() as tx:
            row = await tx.scalar(
                select(ProjectAgentSessionRow).where(
                    ProjectAgentSessionRow.session_uuid == command.agent_session_uuid,
                    ProjectAgentSessionRow.project_id == command.project_uuid,
                )
            )
            # Owner DB may block while this request's short-lived signed
            # Rauthy/peer/Project proof expires. No stale proof may Permit.
            if caller.proof_expires_at <= datetime.now(UTC):
                return None
            if row is None or not permits_current_project_grant(
                row=row,
                actor_uuid=caller.actor_uuid,
                project_uuid=command.project_uuid,
                operation=command.action,
                expected_version=command.expected_grant_revision,
                hand=command.hand,
                tool=command.tool,
                resource=command.resource,
            ):
                return None
            grant = AuthorizedCurrentGrant(
                actor_uuid=caller.actor_uuid,
                project_uuid=row.project_id,
                agent_session_uuid=row.session_uuid,
                grant_revision=row.version,
                expires_at=min(caller.proof_expires_at, row.hard_expires_at),
            )
        # A transaction exit/commit can also block. Do not return a decision
        # whose original identity or grant expired while leaving the scope.
        if grant.expires_at <= datetime.now(UTC):
            return None
        return grant

    async def permits(self, command: DecisionCommand, caller: VerifiedDecisionCaller) -> bool:
        return await self.current_grant(command, caller) is not None


class AuthorizationDecisionService:
    """Coordinates real peer attestation and database/PARC decision."""

    def __init__(
        self,
        attestor: TrustedDecisionAttestor,
        reader: AuthorizationDecisionReader,
    ) -> None:
        self._attestor = attestor
        self._reader = reader

    async def permits(self, request: Request, command: DecisionCommand) -> bool:
        verified = await self._attestor.verify(request, command)
        if not isinstance(verified, VerifiedDecisionCaller):
            return False
        return await self._reader.permits(command, verified)


def authorization_decision_router(
    service: AuthorizationDecisionService | None,
    *,
    resolve_service: Callable[[Request], AuthorizationDecisionService | None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["authorization-private"])

    @router.post("/decide", include_in_schema=False)
    async def decide(request: Request) -> JSONResponse:
        # No FastAPI body-model parameter: it would buffer untrusted bytes
        # BEFORE any identity, peer, length or digest checks.
        try:
            raw, verified_request = await bounded_private_request(request)
            command = DecisionCommand.model_validate_json(raw)
        except PrivateRequestBodyRejected as exc:
            raise HTTPException(exc.status_code, detail=exc.reason, headers=_NO_STORE) from None
        except (ValueError, TypeError):
            raise HTTPException(
                422, detail="invalid bounded decision body", headers=_NO_STORE
            ) from None
        active = (
            service
            if service is not None
            else resolve_service(request)
            if resolve_service is not None
            else None
        )
        if active is None:
            raise HTTPException(
                503, detail="authorization identity attestation unavailable", headers=_NO_STORE
            )
        try:
            async with asyncio.timeout(_DECISION_AUTH_TIMEOUT_SECONDS):
                allowed = await active.permits(verified_request, command)
        except DecisionAuthenticationRequired:
            raise HTTPException(
                401, detail="authorization caller not authenticated", headers=_NO_STORE
            ) from None
        except DecisionScopeDenied:
            raise HTTPException(403, detail="authorization denied", headers=_NO_STORE) from None
        except DecisionAuthorityUnavailable:
            raise HTTPException(
                503, detail="authorization authority unavailable", headers=_NO_STORE
            ) from None
        except Exception:
            raise HTTPException(
                503, detail="authorization authority unavailable", headers=_NO_STORE
            ) from None
        if not allowed:
            raise HTTPException(403, detail="authorization denied", headers=_NO_STORE)
        return JSONResponse(DecisionPermit().model_dump(), headers=_NO_STORE)

    return router
