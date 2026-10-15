"""Rauthy/Platform/Access decision for one bounded Files read, without Identity.

This owner does not mint a bearer or an A6 ProjectPermit, choose a filesystem
root, or read file contents. A Files controller must authenticate the private
response and check it both before reading and before releasing bytes, while
retaining its own root/FD incarnation, path confinement and byte limits.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from authorization._decision_api import (
    AuthorizationDecisionReader,
    AuthorizedCurrentGrant,
    DecisionAuthenticationRequired,
    DecisionAuthorityUnavailable,
    DecisionCommand,
    DecisionScopeDenied,
    TrustedDecisionAttestor,
    VerifiedDecisionCaller,
)
from authorization._resource_scope import (
    EffectResource,
    TrustedResourceOwnerPort,
    VerifiedResourceOwnerProof,
    matches_current_owner,
)

_PROTOCOL = "files-read-decision-v1"
_MAX_BYTES = 262_144
_MAX_VALIDITY = timedelta(seconds=5)
_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class FilesReadDecisionCommand(DecisionCommand):
    """Private exact body authenticated by the existing trusted Files peer."""

    protocol: Literal["files-read-decision-v1"]
    operation_uuid: UUID
    phase: Literal["before_read", "after_read"]
    hand: Literal["files"]
    tool: Literal["read_file"]
    action: Literal["files.read"]
    resource: EffectResource
    expected_resource_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    max_bytes: int = Field(strict=True, ge=1, le=_MAX_BYTES)

    @field_validator("operation_uuid")
    @classmethod
    def operation_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Files read operation must be UUIDv4")
        return value

    @model_validator(mode="after")
    def versioned_files_scope(self) -> FilesReadDecisionCommand:
        if not self.resource.id.startswith("project-path-v1:"):
            raise ValueError("Files read requires the owner-resolved Project path selector")
        return self


class FilesReadDecision(BaseModel):
    """Request-bound private result, NOT transferable authorization evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["files-read-decision-v1"] = _PROTOCOL
    allowed: Literal[True] = True
    operation_uuid: UUID
    phase: Literal["before_read", "after_read"]
    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    hand: Literal["files"] = "files"
    tool: Literal["read_file"] = "read_file"
    action: Literal["files.read"] = "files.read"
    resource: EffectResource
    grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    resource_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    max_bytes: int = Field(strict=True, ge=1, le=_MAX_BYTES)
    checked_at: datetime
    expires_at: datetime


class FilesReadDecisionService:
    def __init__(
        self,
        *,
        attestor: TrustedDecisionAttestor,
        reader: AuthorizationDecisionReader,
        resource_owner: TrustedResourceOwnerPort,
    ) -> None:
        if attestor is None or reader is None or resource_owner is None:
            raise ValueError("Files read needs identity, Access and current Files owner")
        self._attestor = attestor
        self._reader = reader
        self._owner = resource_owner

    def _current_resource(self, command: FilesReadDecisionCommand) -> VerifiedResourceOwnerProof:
        scope = {
            "hand": command.hand,
            "tool": command.tool,
            "action": command.action,
            "resource": command.resource.model_dump(mode="json"),
        }
        try:
            proof = self._owner.verify_current_scope(project_uuid=command.project_uuid, scope=scope)
        except Exception:
            raise DecisionAuthorityUnavailable("Files resource owner unavailable") from None
        if proof is None:
            raise DecisionAuthorityUnavailable("Files resource owner proof absent")
        if (
            not matches_current_owner(proof, project_uuid=command.project_uuid, scope=scope)
            or proof.revision != command.expected_resource_revision
        ):
            raise DecisionScopeDenied("Files resource scope or revision changed")
        return proof

    async def decide(
        self, request: Request, command: FilesReadDecisionCommand
    ) -> FilesReadDecision:
        # Includes signed Rauthy resource-audience, original body-bound Files
        # peer with fresh nonce, and a NEW authoritative Platform membership
        # lookup on every phase. Previous receipt never supplies these facts.
        caller = await self._attestor.verify(request, command)
        if (
            not isinstance(caller, VerifiedDecisionCaller)
            or caller.consumer != "hand"
            or caller.authority != "rauthy"
            or caller.verified_peer_audience != "briareus:access"
            or not isinstance(caller.actor_uuid, UUID)
            or caller.actor_uuid.version != 4
            or caller.project_uuid != command.project_uuid
            or caller.agent_session_uuid != command.agent_session_uuid
            or caller.attested_effect_key != command.effect_key()
            or not isinstance(caller.proof_expires_at, datetime)
            or caller.proof_expires_at.tzinfo is None
            or caller.proof_expires_at <= datetime.now(UTC)
        ):
            raise DecisionAuthenticationRequired("verified Files caller required")
        initial_resource = self._current_resource(command)
        grant = await self._reader.current_grant(command, caller)
        # Defend the protocol boundary EVEN if a future SQL/Cedar reader is
        # incorrectly replaced or returns a stale grant from another scope.
        # None of these owner facts may be reconstructed from a caller POST.
        if (
            not isinstance(grant, AuthorizedCurrentGrant)
            or grant.actor_uuid != caller.actor_uuid
            or grant.project_uuid != command.project_uuid
            or grant.agent_session_uuid != command.agent_session_uuid
            or type(grant.grant_revision) is not int
            or grant.grant_revision != command.expected_grant_revision
            or not isinstance(grant.expires_at, datetime)
            or grant.expires_at.tzinfo is None
            or grant.expires_at > caller.proof_expires_at
            or grant.expires_at <= datetime.now(UTC)
        ):
            raise DecisionScopeDenied("Files read current Access grant denied")
        # SQL or a policy evaluation may consume the original resource proof.
        # A replacement revision cannot silently extend an in-flight read.
        current_resource = self._current_resource(command)
        now = datetime.now(UTC)
        expires_at = min(
            caller.proof_expires_at,
            grant.expires_at,
            initial_resource.expires_at,
            current_resource.expires_at,
            now + _MAX_VALIDITY,
        )
        if expires_at <= now:
            raise DecisionScopeDenied("Files read original authority expired")
        return FilesReadDecision(
            operation_uuid=command.operation_uuid,
            phase=command.phase,
            actor_uuid=grant.actor_uuid,
            project_uuid=grant.project_uuid,
            agent_session_uuid=grant.agent_session_uuid,
            resource=command.resource,
            grant_revision=grant.grant_revision,
            resource_revision=current_resource.revision,
            max_bytes=command.max_bytes,
            checked_at=now,
            expires_at=expires_at,
        )


def files_read_decision_router(
    *, resolve_service: Callable[[], FilesReadDecisionService | None]
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["access-private"])

    @router.post("/files/read-decision", include_in_schema=False)
    async def read_decision(command: FilesReadDecisionCommand, request: Request) -> JSONResponse:
        active = resolve_service()
        if active is None:
            raise HTTPException(503, "Files read authority unavailable", headers=_HEADERS)
        try:
            result = await active.decide(request, command)
        except DecisionAuthenticationRequired:
            raise HTTPException(
                401, "Files read caller not authenticated", headers=_HEADERS
            ) from None
        except DecisionScopeDenied:
            raise HTTPException(403, "Files read denied", headers=_HEADERS) from None
        except Exception:
            # Do not leak provider credentials, path, root, or SQL diagnostics.
            raise HTTPException(503, "Files read authority unavailable", headers=_HEADERS) from None
        return JSONResponse(result.model_dump(mode="json"), headers=_HEADERS)

    return router
