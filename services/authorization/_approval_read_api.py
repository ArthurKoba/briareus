"""Private current Access approval list, scoped by authenticated Project actor.

No browser/session/header-supplied role can authorize listing. The real owner
query reads only Access PostgreSQL and runs after a fresh independently
verified Rauthy+peer+Platform Project membership attestation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from authorization._decision_api import (
    DecisionAuthenticationRequired,
    DecisionAuthorityUnavailable,
    DecisionScopeDenied,
)
from authorization._resource_scope import normalized_resource_grants
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from common.platform_db import PlatformDatabase

_MAX_LIST = 50
_OPERATIONS = frozenset(
    {
        "files.read",
        "files.write",
        "project.metadata.read",
        "terminal.execute",
        "web.access",
        "analysis.import",
        "agents.manage",
        "integrations.use",
        "variables.use",
        "integrations.manage",
        "variables.manage",
    }
)


class ApprovalListCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    limit: int = Field(strict=True, ge=1, le=_MAX_LIST)

    @field_validator("project_uuid")
    @classmethod
    def canonical_uuid(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Project must be UUIDv4")
        return value


class SessionGetCommand(ApprovalListCommand):
    """Exact current AgentSession selector, scoped by trusted Project actor."""

    limit: int = Field(default=1, strict=True, ge=1, le=1)
    session_uuid: UUID

    @field_validator("session_uuid")
    @classmethod
    def canonical_session_uuid(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("AgentSession must be UUIDv4")
        return value


@dataclass(frozen=True, slots=True)
class VerifiedApprovalActor:
    actor_uuid: UUID
    project_uuid: UUID
    can_approve: bool
    issuer: Literal["rauthy"]
    target_audience: Literal["briareus:access"]
    expires_at: datetime


class TrustedApprovalListAttestor(Protocol):
    async def verify(self, request: Request, command: ApprovalListCommand) -> VerifiedApprovalActor:
        """Verify bearer, private peer and fresh current Platform Project role."""
        ...


class ApprovalListReader:
    """Access-owned SQL reader, not a management-BFF SQL join."""

    def __init__(
        self, *, database: PlatformDatabase, attestor: TrustedApprovalListAttestor
    ) -> None:
        if database.engine.url.database != "briareus_access" or attestor is None:
            raise ValueError("approval list must read only trusted Access owner DB")
        self._db = database
        self._attestor = attestor

    async def _verified_actor(
        self, request: Request, command: ApprovalListCommand
    ) -> VerifiedApprovalActor:
        if len(request.headers.getlist("authorization")) != 1 or request.headers.get("cookie"):
            raise DecisionAuthenticationRequired
        try:
            actor = await self._attestor.verify(request, command)
        except (
            DecisionAuthenticationRequired,
            DecisionAuthorityUnavailable,
            DecisionScopeDenied,
        ):
            raise
        except Exception:
            raise DecisionAuthorityUnavailable from None
        now = datetime.now(UTC)
        if (
            not isinstance(actor, VerifiedApprovalActor)
            or not isinstance(actor.actor_uuid, UUID)
            or actor.actor_uuid.version != 4
            or actor.project_uuid != command.project_uuid
            or type(actor.can_approve) is not bool
            or actor.issuer != "rauthy"
            or actor.target_audience != "briareus:access"
            or not isinstance(actor.expires_at, datetime)
            or actor.expires_at.tzinfo is None
            or not now < actor.expires_at <= now + timedelta(seconds=30)
        ):
            raise DecisionScopeDenied
        return actor

    async def list(self, request: Request, command: ApprovalListCommand) -> list[dict[str, object]]:
        actor = await self._verified_actor(request, command)
        now = datetime.now(UTC)
        query = select(SessionApprovalRow).where(
            SessionApprovalRow.project_id == command.project_uuid
        )
        if not actor.can_approve:
            query = query.where(SessionApprovalRow.requested_by_user_id == actor.actor_uuid)
        query = query.order_by(
            SessionApprovalRow.created_at.desc(), SessionApprovalRow.id.desc()
        ).limit(command.limit)
        async with self._db.transaction() as tx:
            rows = list(await tx.scalars(query))
            if len(rows) > command.limit:
                raise DecisionAuthorityUnavailable
            now = datetime.now(UTC)
            result: list[dict[str, object]] = []
            for row in rows:
                if (
                    row.project_id != command.project_uuid
                    or (not actor.can_approve and row.requested_by_user_id != actor.actor_uuid)
                    or not isinstance(row.id, UUID)
                    or row.id.version != 4
                    or not isinstance(row.session_uuid, UUID)
                    or row.session_uuid.version != 4
                    or not isinstance(row.requested_by_user_id, UUID)
                    or row.requested_by_user_id.version != 4
                    or type(row.version) is not int
                    or row.version < 1
                    or row.status not in {"pending", "approved", "rejected"}
                    or not isinstance(row.requested_expires_at, datetime)
                    or row.requested_expires_at.tzinfo is None
                    or (
                        row.resolved_by_user_id is not None
                        and (
                            not isinstance(row.resolved_by_user_id, UUID)
                            or row.resolved_by_user_id.version != 4
                        )
                    )
                    or (
                        row.issued_session_uuid is not None
                        and (
                            not isinstance(row.issued_session_uuid, UUID)
                            or row.issued_session_uuid.version != 4
                        )
                    )
                    or not isinstance(row.requested_grants, dict)
                ):
                    raise DecisionAuthorityUnavailable
                operations = row.requested_grants.get("operations", [])
                if (
                    not isinstance(operations, list)
                    or not 1 <= len(operations) <= 32
                    or not all(isinstance(op, str) and op in _OPERATIONS for op in operations)
                    or len(set(operations)) != len(operations)
                ):
                    raise DecisionAuthorityUnavailable
                try:
                    resources = normalized_resource_grants(
                        row.requested_grants.get("resources", []),
                        allowed_actions=set(operations),
                        project_uuid=command.project_uuid,
                    )
                except ValueError:
                    raise DecisionAuthorityUnavailable from None
                actions: list[str] = []
                if (
                    actor.can_approve
                    and row.requested_by_user_id != actor.actor_uuid
                    and row.status == "pending"
                    and row.requested_expires_at > now
                ):
                    actions = ["approve", "deny"]
                result.append(
                    {
                        "id": str(row.id),
                        "project_uuid": str(row.project_id),
                        "agent_session_uuid": str(row.session_uuid),
                        "requested_by_user_uuid": str(row.requested_by_user_id),
                        "status": row.status,
                        "version": row.version,
                        "requested_operations": operations,
                        "requested_resources": resources,
                        "requested_expires_at": row.requested_expires_at.isoformat(),
                        "resolved_by_user_uuid": (
                            str(row.resolved_by_user_id)
                            if row.resolved_by_user_id is not None
                            else None
                        ),
                        "issued_session_uuid": (
                            str(row.issued_session_uuid)
                            if row.issued_session_uuid is not None
                            else None
                        ),
                        "allowed_actions": actions,
                    }
                )
        if actor.expires_at <= datetime.now(UTC):
            raise DecisionAuthorityUnavailable
        return result

    async def list_sessions(
        self, request: Request, command: ApprovalListCommand
    ) -> list[dict[str, object]]:
        """Current, version-fenced sessions visible only to verified Project actors."""
        actor = await self._verified_actor(request, command)
        now = datetime.now(UTC)
        query = select(ProjectAgentSessionRow).where(
            ProjectAgentSessionRow.project_id == command.project_uuid
        )
        if not actor.can_approve:
            query = query.where(ProjectAgentSessionRow.created_by_principal_id == actor.actor_uuid)
        if isinstance(command, SessionGetCommand):
            query = query.where(ProjectAgentSessionRow.session_uuid == command.session_uuid)
        query = query.order_by(
            ProjectAgentSessionRow.created_at.desc(),
            ProjectAgentSessionRow.session_uuid.desc(),
        ).limit(command.limit)
        async with self._db.transaction() as tx:
            rows = list(await tx.scalars(query))
            if len(rows) > command.limit:
                raise DecisionAuthorityUnavailable
            now = datetime.now(UTC)
            result: list[dict[str, object]] = []
            for row in rows:
                if (
                    row.project_id != command.project_uuid
                    or not isinstance(row.session_uuid, UUID)
                    or row.session_uuid.version != 4
                    or not isinstance(row.created_by_principal_id, UUID)
                    or row.created_by_principal_id.version != 4
                    or (not actor.can_approve and row.created_by_principal_id != actor.actor_uuid)
                    or type(row.version) is not int
                    or row.version < 1
                    or row.status not in {"active", "revoked"}
                    or type(row.is_elevated) is not bool
                    or row.elevation_policy not in {"fixed", "requestable"}
                    or not isinstance(row.hard_expires_at, datetime)
                    or row.hard_expires_at.tzinfo is None
                    or (row.status == "active" and row.revoked_at is not None)
                    or (row.status == "revoked" and row.revoked_at is None)
                    or not isinstance(row.grants, dict)
                ):
                    raise DecisionAuthorityUnavailable
                operations = row.grants.get("operations")
                if (
                    not isinstance(operations, list)
                    or not 1 <= len(operations) <= 32
                    or any(
                        not isinstance(operation, str) or operation not in _OPERATIONS
                        for operation in operations
                    )
                    or len(set(operations)) != len(operations)
                ):
                    raise DecisionAuthorityUnavailable
                try:
                    resources = normalized_resource_grants(
                        row.grants.get("resources", []),
                        allowed_actions=set(operations),
                        project_uuid=command.project_uuid,
                    )
                except ValueError:
                    raise DecisionAuthorityUnavailable from None
                current_status = (
                    "expired"
                    if row.status == "active" and row.hard_expires_at <= now
                    else row.status
                )
                result.append(
                    {
                        "session_uuid": str(row.session_uuid),
                        "project_uuid": str(row.project_id),
                        "created_by_user_uuid": str(row.created_by_principal_id),
                        "revision": row.version,
                        "status": current_status,
                        "is_elevated": row.is_elevated,
                        "elevation_policy": row.elevation_policy,
                        "hard_expires_at": row.hard_expires_at.isoformat(),
                        "operations": list(operations),
                        "resources": resources,
                        "allowed_actions": (
                            ["revoke"] if actor.can_approve and current_status == "active" else []
                        ),
                    }
                )
        if actor.expires_at <= datetime.now(UTC):
            raise DecisionAuthorityUnavailable
        return result


def private_approval_list_router(
    *,
    resolve_reader: Callable[[], ApprovalListReader | None],
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["access-private"])

    @router.post("/approvals/list", include_in_schema=False)
    async def list_approvals(command: ApprovalListCommand, request: Request) -> JSONResponse:
        active = resolve_reader()
        if active is None:
            raise HTTPException(503, detail="approval authority unavailable")
        try:
            entries = await active.list(request, command)
        except DecisionAuthenticationRequired:
            raise HTTPException(401, detail="approval caller not authenticated") from None
        except DecisionScopeDenied:
            raise HTTPException(403, detail="approval Project scope denied") from None
        except Exception:
            raise HTTPException(503, detail="approval authority unavailable") from None
        return JSONResponse(
            {"items": entries},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @router.post("/sessions/list", include_in_schema=False)
    async def list_sessions(command: ApprovalListCommand, request: Request) -> JSONResponse:
        active = resolve_reader()
        if active is None:
            raise HTTPException(503, detail="session read authority unavailable")
        try:
            entries = await active.list_sessions(request, command)
        except DecisionAuthenticationRequired:
            raise HTTPException(401, detail="session read caller not authenticated") from None
        except DecisionScopeDenied:
            raise HTTPException(403, detail="session read Project scope denied") from None
        except Exception:
            raise HTTPException(503, detail="session read authority unavailable") from None
        return JSONResponse(
            {"items": entries},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @router.post("/sessions/get", include_in_schema=False)
    async def get_session(command: SessionGetCommand, request: Request) -> JSONResponse:
        active = resolve_reader()
        if active is None:
            raise HTTPException(503, detail="session detail authority unavailable")
        try:
            entries = await active.list_sessions(request, command)
        except DecisionAuthenticationRequired:
            raise HTTPException(401, detail="session detail caller not authenticated") from None
        except DecisionScopeDenied:
            raise HTTPException(403, detail="session detail Project scope denied") from None
        except Exception:
            raise HTTPException(503, detail="session detail authority unavailable") from None
        if len(entries) > 1:
            raise HTTPException(503, detail="session detail owner inconsistent")
        if not entries:
            raise HTTPException(
                404,
                detail="AgentSession not found",
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        if entries[0].get("session_uuid") != str(command.session_uuid):
            raise HTTPException(503, detail="session detail owner selector mismatch")
        return JSONResponse(
            {"item": entries[0]},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    return router
