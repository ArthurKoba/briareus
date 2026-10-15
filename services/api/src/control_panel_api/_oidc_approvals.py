"""Authenticated Control Panel API for current AgentSession requests and grants.

This router cannot authorize with Rauthy identity alone. Current Platform
proof gates visibility, while an independent Authorization owner port must
recheck the actor/Project/approver, signed peer and durable transaction state.
No owner port is installed in the default release, so no write can succeed.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ._api_paths import API_V1_PREFIX
from ._oidc_membership import CurrentPlatformContext, ResolvedPlatformUser
from ._oidc_origin_policy import PUBLIC_ORIGIN, local_browser_host

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_MAX_APPROVALS = 50
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


@dataclass(frozen=True, slots=True)
class ApprovalSnapshot:
    approval_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    requested_by_user_uuid: UUID
    status: Literal["pending", "approved", "rejected"]
    version: int
    requested_operations: tuple[str, ...]
    requested_resources: tuple[dict[str, object], ...]
    requested_expires_at: datetime
    resolved_by_user_uuid: UUID | None = None
    issued_session_uuid: UUID | None = None


@dataclass(frozen=True, slots=True)
class OpenSessionSnapshot:
    session_uuid: UUID
    project_uuid: UUID
    revision: int
    status: Literal["active"]
    is_elevated: Literal[False]
    elevation_policy: Literal["fixed", "requestable"]
    hard_expires_at: datetime
    operations: tuple[str, ...]
    resources: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class CurrentSessionSnapshot:
    session_uuid: UUID
    project_uuid: UUID
    created_by_user_uuid: UUID
    revision: int
    status: Literal["active", "revoked", "expired"]
    is_elevated: bool
    elevation_policy: Literal["fixed", "requestable"]
    hard_expires_at: datetime
    operations: tuple[str, ...]
    resources: tuple[dict[str, object], ...]
    allowed_actions: tuple[Literal["revoke"], ...]


@dataclass(frozen=True, slots=True)
class GrantSnapshot:
    session_uuid: UUID
    project_uuid: UUID
    status: Literal["active", "revoked"]
    revision: int


class OwnerManagementUnavailable(Exception):
    """Trusted Authorization owner or fresh permission proof unavailable."""


class OwnerManagementDenied(Exception):
    """Actual owner denied this actor/Project/request scope."""


class OwnerManagementConflict(Exception):
    """Owner detected stale revision or idempotency conflict."""


class OwnerManagementNotFound(Exception):
    """A scoped session is absent or not visible to this current actor."""


class OwnerManagementInvalidInput(Exception):
    """Actual Access owner rejected an invalid scoped command."""


class ApprovalManagementPort(Protocol):
    """Server-side authenticated transport to Authorization's owner API."""

    async def open_normal(
        self,
        *,
        actor: UUID,
        project: UUID,
        elevation_policy: Literal["fixed", "requestable"],
        label: str | None,
        operation: UUID,
    ) -> OpenSessionSnapshot: ...

    async def list_sessions(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[CurrentSessionSnapshot, ...]: ...

    async def get_session(
        self, *, actor: UUID, project: UUID, session: UUID
    ) -> CurrentSessionSnapshot: ...

    async def list_approvals(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[ApprovalSnapshot, ...]: ...

    async def request_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        operations: tuple[str, ...],
        resources: tuple[dict[str, object], ...],
        seconds: int,
        expected_grant_revision: int,
        operation: UUID,
    ) -> ApprovalSnapshot: ...

    async def resolve_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        approval: UUID,
        expected_version: int,
        approve: bool,
        allowed_operations: tuple[str, ...] | None,
        operation: UUID,
    ) -> ApprovalSnapshot: ...

    async def revoke_session(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        expected_revision: int,
        operation: UUID,
    ) -> GrantSnapshot: ...


class ResourceScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1, max_length=64)
    id: str = Field(min_length=1, max_length=512)


class ScopedEffectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hand: Literal["files", "terminal", "web", "svc", "reverse", "infrastructure"]
    tool: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    resource: ResourceScopeRequest


class OpenSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    elevation_policy: Literal["fixed", "requestable"] = "requestable"
    label: str | None = Field(default=None, max_length=128)


class RequestElevation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    agent_session_uuid: UUID
    operations: tuple[str, ...] = Field(min_length=1, max_length=32)
    resources: tuple[ScopedEffectRequest, ...] = Field(default=(), max_length=32)
    seconds: int = Field(strict=True, ge=1, le=300)
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)


class ResolveElevation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    approve: bool = Field(strict=True)
    expected_approval_version: int = Field(strict=True, ge=1, le=2**63 - 1)
    allowed_operations: tuple[str, ...] | None = Field(default=None, max_length=32)


class RevokeSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)


def approval_management_router(
    *,
    current_context: CurrentPlatformContext,
    owner: ApprovalManagementPort | None,
    test_only_local_origin: str | None = None,
) -> APIRouter:
    expected_host = local_browser_host(test_only_local_origin)
    expected_origin = test_only_local_origin or PUBLIC_ORIGIN
    router = APIRouter()

    def fail(status: int, code: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code}},
            headers=_NO_STORE,
        )

    def project_access(proof: ResolvedPlatformUser, project_uuid: UUID, *, approve: bool) -> bool:
        for item in proof.projects:
            if item.project_uuid == project_uuid:
                return (
                    "approve_agent_session" in item.permissions
                    if approve
                    else "use_resources" in item.permissions
                )
        return False

    async def verified(request: Request, project_uuid: UUID) -> ResolvedPlatformUser | JSONResponse:
        current = await current_context(request, project_uuid)
        if isinstance(current, JSONResponse):
            return current
        session, proof = current
        # Browser cookie expiry and current Platform proof expiry are
        # independent. Keep the earlier one for subsequent slow owner IO.
        return replace(proof, expires_at=min(proof.expires_at, session.expires_at))

    def mutate(request: Request) -> UUID | JSONResponse:
        if (
            request.headers.getlist("origin") != [expected_origin]
            or (expected_host is not None and request.headers.getlist("host") != [expected_host])
            or request.headers.getlist("content-type") != ["application/json"]
        ):
            return fail(403, "APPROVAL_ORIGIN_REQUIRED")
        operation_headers = request.headers.getlist("operation-uuid")
        idempotency_headers = request.headers.getlist("idempotency-key")
        if len(operation_headers) != 1 or idempotency_headers != operation_headers:
            return fail(422, "APPROVAL_OPERATION_ID_REQUIRED")
        try:
            operation = UUID(operation_headers[0])
        except (ValueError, AttributeError):
            return fail(422, "APPROVAL_OPERATION_ID_INVALID")
        if operation.version != 4 or str(operation) != operation_headers[0]:
            return fail(422, "APPROVAL_OPERATION_ID_INVALID")
        return operation

    def snapshot(item: ApprovalSnapshot, actor: UUID, *, approver: bool) -> dict[str, object]:
        return {
            "id": str(item.approval_uuid),
            "project_uuid": str(item.project_uuid),
            "agent_session_uuid": str(item.agent_session_uuid),
            "requested_by_user_uuid": str(item.requested_by_user_uuid),
            "status": item.status,
            "version": item.version,
            "requested_operations": list(item.requested_operations),
            "requested_resources": list(item.requested_resources),
            "requested_expires_at": item.requested_expires_at.isoformat(),
            "resolved_by_user_uuid": (
                str(item.resolved_by_user_uuid) if item.resolved_by_user_uuid else None
            ),
            "issued_session_uuid": (
                str(item.issued_session_uuid) if item.issued_session_uuid else None
            ),
            "allowed_actions": (
                ["approve", "deny"]
                if item.status == "pending"
                and approver
                and item.requested_by_user_uuid != actor
                and item.requested_expires_at > datetime.now(UTC)
                else []
            ),
        }

    def valid_snapshot(item: object, project: UUID) -> bool:
        return (
            isinstance(item, ApprovalSnapshot)
            and isinstance(item.approval_uuid, UUID)
            and item.approval_uuid.version == 4
            and item.project_uuid == project
            and isinstance(item.agent_session_uuid, UUID)
            and item.agent_session_uuid.version == 4
            and isinstance(item.requested_by_user_uuid, UUID)
            and item.requested_by_user_uuid.version == 4
            and type(item.version) is int
            and item.version >= 1
            and item.status in {"pending", "approved", "rejected"}
            and isinstance(item.requested_expires_at, datetime)
            and item.requested_expires_at.tzinfo is not None
            and isinstance(item.requested_operations, tuple)
            and 1 <= len(item.requested_operations) <= 32
            and all(isinstance(op, str) and op in _OPERATIONS for op in item.requested_operations)
            and len(set(item.requested_operations)) == len(item.requested_operations)
            and isinstance(item.requested_resources, tuple)
            and len(item.requested_resources) <= 32
            and (
                item.resolved_by_user_uuid is None
                or (
                    isinstance(item.resolved_by_user_uuid, UUID)
                    and item.resolved_by_user_uuid.version == 4
                )
            )
            and (
                item.issued_session_uuid is None
                or (
                    isinstance(item.issued_session_uuid, UUID)
                    and item.issued_session_uuid.version == 4
                )
            )
            and (
                (
                    item.status == "pending"
                    and item.resolved_by_user_uuid is None
                    and item.issued_session_uuid is None
                )
                or (
                    item.status in {"approved", "rejected"}
                    and item.resolved_by_user_uuid is not None
                    and item.resolved_by_user_uuid != item.requested_by_user_uuid
                    and ((item.status == "approved") == (item.issued_session_uuid is not None))
                    and item.issued_session_uuid != item.agent_session_uuid
                )
            )
            and valid_approval_resources(item)
        )

    def valid_approval_resources(item: ApprovalSnapshot) -> bool:
        seen: set[ScopedEffectRequest] = set()
        for value in item.requested_resources:
            try:
                resource = ScopedEffectRequest.model_validate(value)
            except ValueError:
                return False
            if resource.action not in item.requested_operations or resource in seen:
                return False
            seen.add(resource)
        return True

    async def run_owner(
        call: Awaitable[object], *, proof: ResolvedPlatformUser
    ) -> object | JSONResponse:
        try:
            outcome = await call
            if proof.expires_at <= datetime.now(UTC):
                return fail(503, "PLATFORM_PROOF_EXPIRED")
            return outcome
        except OwnerManagementDenied:
            return fail(403, "APPROVAL_PERMISSION_DENIED")
        except OwnerManagementNotFound:
            if proof.expires_at <= datetime.now(UTC):
                return fail(503, "PLATFORM_PROOF_EXPIRED")
            return fail(404, "AGENT_SESSION_NOT_FOUND")
        except OwnerManagementConflict:
            return fail(409, "APPROVAL_REVISION_CONFLICT")
        except OwnerManagementInvalidInput:
            return fail(422, "APPROVAL_SCOPE_INVALID")
        except Exception:
            # Never leak owner service response, credentials or exception text.
            return fail(503, "APPROVAL_OWNER_UNAVAILABLE")

    @router.get(API_V1_PREFIX + "/approvals")
    async def list_pending(request: Request, project_uuid: UUID) -> JSONResponse:
        proof = await verified(request, project_uuid)
        if isinstance(proof, JSONResponse):
            return proof
        if project_uuid.version != 4 or not (
            project_access(proof, project_uuid, approve=False)
            or project_access(proof, project_uuid, approve=True)
        ):
            return fail(403, "PROJECT_ACCESS_DENIED")
        if owner is None:
            return fail(503, "APPROVAL_OWNER_UNAVAILABLE")
        result = await run_owner(
            owner.list_approvals(actor=proof.user_uuid, project=project_uuid, limit=_MAX_APPROVALS),
            proof=proof,
        )
        if isinstance(result, JSONResponse):
            return result
        if (
            not isinstance(result, tuple)
            or len(result) > _MAX_APPROVALS
            or any(not valid_snapshot(item, project_uuid) for item in result)
            or len({item.approval_uuid for item in result}) != len(result)
            or (
                not project_access(proof, project_uuid, approve=True)
                and any(item.requested_by_user_uuid != proof.user_uuid for item in result)
            )
        ):
            return fail(503, "APPROVAL_OWNER_INVALID_RESPONSE")
        may_approve = project_access(proof, project_uuid, approve=True)
        return JSONResponse(
            {"items": [snapshot(item, proof.user_uuid, approver=may_approve) for item in result]},
            headers=_NO_STORE,
        )

    def session_records(
        result: object, *, proof: ResolvedPlatformUser, project_uuid: UUID, approval_right: bool
    ) -> list[dict[str, object]] | JSONResponse:
        if not isinstance(result, tuple) or len(result) > _MAX_APPROVALS:
            return fail(503, "AGENT_SESSION_OWNER_INVALID_RESPONSE")
        now = datetime.now(UTC)
        seen: set[UUID] = set()
        records: list[dict[str, object]] = []
        for item in result:
            if (
                not isinstance(item, CurrentSessionSnapshot)
                or not isinstance(item.session_uuid, UUID)
                or item.session_uuid.version != 4
                or item.session_uuid in seen
                or item.project_uuid != project_uuid
                or not isinstance(item.created_by_user_uuid, UUID)
                or item.created_by_user_uuid.version != 4
                or (not approval_right and item.created_by_user_uuid != proof.user_uuid)
                or type(item.revision) is not int
                or item.revision < 1
                or item.status not in {"active", "revoked", "expired"}
                or type(item.is_elevated) is not bool
                or item.elevation_policy not in {"fixed", "requestable"}
                or not isinstance(item.hard_expires_at, datetime)
                or item.hard_expires_at.tzinfo is None
                or (item.status == "active" and item.hard_expires_at <= now)
                or (item.status == "expired" and item.hard_expires_at > now)
                or not isinstance(item.operations, tuple)
                or not 1 <= len(item.operations) <= 32
                or any(
                    not isinstance(operation, str) or operation not in _OPERATIONS
                    for operation in item.operations
                )
                or len(set(item.operations)) != len(item.operations)
                or not isinstance(item.resources, tuple)
                or len(item.resources) > 32
                or not isinstance(item.allowed_actions, tuple)
                or item.allowed_actions not in ((), ("revoke",))
                or (
                    item.allowed_actions
                    and (
                        not approval_right or item.status != "active" or item.hard_expires_at <= now
                    )
                )
            ):
                return fail(503, "AGENT_SESSION_OWNER_INVALID_RESPONSE")
            for scope in item.resources:
                try:
                    effect = ScopedEffectRequest.model_validate(scope)
                except ValueError:
                    return fail(503, "AGENT_SESSION_OWNER_INVALID_RESPONSE")
                if effect.action not in item.operations:
                    return fail(503, "AGENT_SESSION_OWNER_INVALID_RESPONSE")
            seen.add(item.session_uuid)
            records.append(
                {
                    "session_uuid": str(item.session_uuid),
                    "project_uuid": str(item.project_uuid),
                    "created_by_user_uuid": str(item.created_by_user_uuid),
                    "revision": item.revision,
                    "status": item.status,
                    "is_elevated": item.is_elevated,
                    "elevation_policy": item.elevation_policy,
                    "hard_expires_at": item.hard_expires_at.isoformat(),
                    "operations": list(item.operations),
                    "resources": list(item.resources),
                    "allowed_actions": list(item.allowed_actions),
                }
            )
        return records

    @router.get(API_V1_PREFIX + "/agent-sessions")
    async def current_sessions(request: Request, project_uuid: UUID) -> JSONResponse:
        proof = await verified(request, project_uuid)
        if isinstance(proof, JSONResponse):
            return proof
        resource_right = project_access(proof, project_uuid, approve=False)
        approval_right = project_access(proof, project_uuid, approve=True)
        if project_uuid.version != 4 or not (resource_right or approval_right):
            return fail(403, "PROJECT_ACCESS_DENIED")
        if owner is None:
            return fail(503, "APPROVAL_OWNER_UNAVAILABLE")
        result = await run_owner(
            owner.list_sessions(actor=proof.user_uuid, project=project_uuid, limit=_MAX_APPROVALS),
            proof=proof,
        )
        if isinstance(result, JSONResponse):
            return result
        records = session_records(
            result, proof=proof, project_uuid=project_uuid, approval_right=approval_right
        )
        if isinstance(records, JSONResponse):
            return records
        return JSONResponse({"items": records}, headers=_NO_STORE)

    @router.get(API_V1_PREFIX + "/agent-sessions/{session_uuid}")
    async def current_session(
        request: Request, session_uuid: UUID, project_uuid: UUID
    ) -> JSONResponse:
        proof = await verified(request, project_uuid)
        if isinstance(proof, JSONResponse):
            return proof
        approval_right = project_access(proof, project_uuid, approve=True)
        if project_uuid.version != 4 or not (
            approval_right or project_access(proof, project_uuid, approve=False)
        ):
            return fail(403, "PROJECT_ACCESS_DENIED")
        if session_uuid.version != 4:
            return fail(422, "AGENT_SESSION_INVALID")
        if owner is None:
            return fail(503, "APPROVAL_OWNER_UNAVAILABLE")
        result = await run_owner(
            owner.get_session(actor=proof.user_uuid, project=project_uuid, session=session_uuid),
            proof=proof,
        )
        if isinstance(result, JSONResponse):
            return result
        if not isinstance(result, CurrentSessionSnapshot) or result.session_uuid != session_uuid:
            return fail(503, "AGENT_SESSION_OWNER_INVALID_RESPONSE")
        records = session_records(
            (result,), proof=proof, project_uuid=project_uuid, approval_right=approval_right
        )
        if isinstance(records, JSONResponse):
            return records
        return JSONResponse(records[0], headers=_NO_STORE)

    async def require_write(
        request: Request, project_uuid: UUID, *, approve: bool
    ) -> tuple[ResolvedPlatformUser, UUID] | JSONResponse:
        proof = await verified(request, project_uuid)
        if isinstance(proof, JSONResponse):
            return proof
        if project_uuid.version != 4 or not project_access(proof, project_uuid, approve=approve):
            return fail(403, "PROJECT_PERMISSION_DENIED")
        operation = mutate(request)
        if isinstance(operation, JSONResponse):
            return operation
        if owner is None:
            return fail(503, "APPROVAL_OWNER_UNAVAILABLE")
        return proof, operation

    @router.post(API_V1_PREFIX + "/agent-sessions")
    async def open_session(request: Request, body: OpenSessionRequest) -> JSONResponse:
        authorized = await require_write(request, body.project_uuid, approve=False)
        if isinstance(authorized, JSONResponse):
            return authorized
        proof, operation = authorized
        if body.label is not None and (
            not body.label
            or body.label != body.label.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in body.label)
        ):
            return fail(422, "AGENT_SESSION_LABEL_INVALID")
        result = await run_owner(
            owner.open_normal(
                actor=proof.user_uuid,
                project=body.project_uuid,
                elevation_policy=body.elevation_policy,
                label=body.label,
                operation=operation,
            ),
            proof=proof,
        )
        if isinstance(result, JSONResponse):
            return result
        if (
            not isinstance(result, OpenSessionSnapshot)
            or result.session_uuid.version != 4
            or result.project_uuid != body.project_uuid
            or result.status != "active"
            or result.is_elevated is not False
            or result.elevation_policy != body.elevation_policy
            or type(result.revision) is not int
            or result.revision != 1
            or result.hard_expires_at.tzinfo is None
            or result.hard_expires_at <= datetime.now(UTC)
            or result.hard_expires_at > datetime.now(UTC) + timedelta(hours=24)
            or result.operations != ("files.read", "project.metadata.read")
            or result.resources
        ):
            return fail(503, "APPROVAL_OWNER_INVALID_RESPONSE")
        return JSONResponse(
            {
                "session_uuid": str(result.session_uuid),
                "project_uuid": str(result.project_uuid),
                "revision": result.revision,
                "status": result.status,
                "is_elevated": False,
                "elevation_policy": result.elevation_policy,
                "hard_expires_at": result.hard_expires_at.isoformat(),
                "operations": list(result.operations),
                "resources": [],
            },
            status_code=201,
            headers=_NO_STORE,
        )

    @router.post(API_V1_PREFIX + "/approvals")
    async def request_elevation(request: Request, body: RequestElevation) -> JSONResponse:
        authorized = await require_write(request, body.project_uuid, approve=False)
        if isinstance(authorized, JSONResponse):
            return authorized
        proof, operation = authorized
        if (
            body.agent_session_uuid.version != 4
            or not set(body.operations).issubset(_OPERATIONS)
            or len(set(body.operations)) != len(body.operations)
            or {item.action for item in body.resources} != set(body.operations)
            or len(set(body.resources)) != len(body.resources)
        ):
            return fail(422, "APPROVAL_SCOPE_INVALID")
        result = await run_owner(
            owner.request_elevation(
                actor=proof.user_uuid,
                project=body.project_uuid,
                session=body.agent_session_uuid,
                operations=body.operations,
                resources=tuple(item.model_dump(mode="json") for item in body.resources),
                seconds=body.seconds,
                expected_grant_revision=body.expected_grant_revision,
                operation=operation,
            ),
            proof=proof,
        )
        if isinstance(result, JSONResponse):
            return result
        if (
            not valid_snapshot(result, body.project_uuid)
            or result.requested_by_user_uuid != proof.user_uuid
            or result.agent_session_uuid != body.agent_session_uuid
            or result.status != "pending"
            or result.version != 1
            or result.approval_uuid != operation
            or set(result.requested_operations) != set(body.operations)
            or {ScopedEffectRequest.model_validate(scope) for scope in result.requested_resources}
            != set(body.resources)
        ):
            return fail(503, "APPROVAL_OWNER_INVALID_RESPONSE")
        return JSONResponse(
            snapshot(result, proof.user_uuid, approver=False),
            status_code=202,
            headers=_NO_STORE,
        )

    @router.post(API_V1_PREFIX + "/approvals/{approval_uuid}/resolve")
    async def resolve_elevation(
        request: Request, approval_uuid: UUID, body: ResolveElevation
    ) -> JSONResponse:
        authorized = await require_write(request, body.project_uuid, approve=True)
        if isinstance(authorized, JSONResponse):
            return authorized
        proof, operation = authorized
        if approval_uuid.version != 4 or (
            body.allowed_operations is not None
            and (
                len(set(body.allowed_operations)) != len(body.allowed_operations)
                or not set(body.allowed_operations).issubset(_OPERATIONS)
            )
        ):
            return fail(422, "APPROVAL_SCOPE_INVALID")
        result = await run_owner(
            owner.resolve_elevation(
                actor=proof.user_uuid,
                project=body.project_uuid,
                approval=approval_uuid,
                expected_version=body.expected_approval_version,
                approve=body.approve,
                allowed_operations=body.allowed_operations,
                operation=operation,
            ),
            proof=proof,
        )
        if isinstance(result, JSONResponse):
            return result
        if (
            not valid_snapshot(result, body.project_uuid)
            or result.approval_uuid != approval_uuid
            or result.requested_by_user_uuid == proof.user_uuid
            or result.resolved_by_user_uuid != proof.user_uuid
            or result.version != body.expected_approval_version + 1
            or result.status != ("approved" if body.approve else "rejected")
        ):
            return fail(503, "APPROVAL_OWNER_INVALID_RESPONSE")
        return JSONResponse(
            snapshot(result, proof.user_uuid, approver=True),
            headers=_NO_STORE,
        )

    @router.post(API_V1_PREFIX + "/agent-sessions/{session_uuid}/revoke")
    async def revoke_session(
        request: Request, session_uuid: UUID, body: RevokeSession
    ) -> JSONResponse:
        authorized = await require_write(request, body.project_uuid, approve=True)
        if isinstance(authorized, JSONResponse):
            return authorized
        proof, operation = authorized
        if session_uuid.version != 4:
            return fail(422, "AGENT_SESSION_INVALID")
        result = await run_owner(
            owner.revoke_session(
                actor=proof.user_uuid,
                project=body.project_uuid,
                session=session_uuid,
                expected_revision=body.expected_grant_revision,
                operation=operation,
            ),
            proof=proof,
        )
        if isinstance(result, JSONResponse):
            return result
        if (
            not isinstance(result, GrantSnapshot)
            or result.project_uuid != body.project_uuid
            or result.session_uuid != session_uuid
            or result.status != "revoked"
            or type(result.revision) is not int
            or result.revision <= body.expected_grant_revision
        ):
            return fail(503, "APPROVAL_OWNER_INVALID_RESPONSE")
        return JSONResponse(
            {
                "session_uuid": str(result.session_uuid),
                "project_uuid": str(result.project_uuid),
                "status": "revoked",
                "revision": result.revision,
            },
            headers=_NO_STORE,
        )

    return router
