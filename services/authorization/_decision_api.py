"""Private Gateway/Hand authorization boundary backed by Access SQL and Cedar.

No user IDs or permissions from request headers/body are trusted. The attestor
is injected ONLY by independently verified Rauthy + service-peer integration.
Without it, the route is mounted but unavailable and cannot grant access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from authorization._access_cedar import permits_current_project_grant
from authorization._session_persistence import ProjectAgentSessionRow
from common.platform_db import PlatformDatabase


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
    expected_grant_revision: int = Field(ge=1)

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

    async def permits(self, command: DecisionCommand, caller: VerifiedDecisionCaller) -> bool:
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
        ):
            return False
        async with self._db.transaction() as tx:
            row = await tx.scalar(
                select(ProjectAgentSessionRow).where(
                    ProjectAgentSessionRow.session_uuid == command.agent_session_uuid,
                    ProjectAgentSessionRow.project_id == command.project_uuid,
                )
            )
            return row is not None and permits_current_project_grant(
                row=row,
                actor_uuid=caller.actor_uuid,
                project_uuid=command.project_uuid,
                operation=command.action,
                expected_version=command.expected_grant_revision,
            )


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
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["authorization-private"])

    @router.post("/decide", include_in_schema=False)
    async def decide(command: DecisionCommand, request: Request) -> DecisionPermit:
        if service is None:
            raise HTTPException(503, detail="authorization identity attestation unavailable")
        try:
            allowed = await service.permits(request, command)
        except DecisionAuthenticationRequired:
            raise HTTPException(401, detail="authorization caller not authenticated") from None
        except DecisionScopeDenied:
            raise HTTPException(403, detail="authorization denied") from None
        except DecisionAuthorityUnavailable:
            raise HTTPException(503, detail="authorization authority unavailable") from None
        except Exception:
            # No grace grants or fallback to management state, unsigned headers,
            # a cached JWT, or the caller-supplied expected revision.
            raise HTTPException(503, detail="authorization authority unavailable") from None
        if not allowed:
            raise HTTPException(403, detail="authorization denied")
        return DecisionPermit()

    return router

