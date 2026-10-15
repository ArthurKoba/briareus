"""Rauthy-only, Access-owned AgentSession request/approval/revoke commands.

This is the NEW greenfield command path. It does not require an obsolete
Identity database, legacy owner JWT, a second User password, or cross-owner
SQL. Trusted current Rauthy+Platform+service-peer evidence is injected and
checked again before *every* Access SQL operation and idempotent replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._idempotency import CommandOutcome, IdempotentCommandExecutor
from authorization._platform_persistence import OutboxRow, SecurityAuditRow
from authorization._resource_scope import (
    TrustedResourceOwnerPort,
    matches_current_owner,
    normalized_resource_grants,
)
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, Conflict

_MAX_LIFETIME_SECONDS = 300
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


class ScopeResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str = Field(min_length=1, max_length=64)
    id: str = Field(min_length=1, max_length=512)


class ScopeEffect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hand: Literal["files", "terminal", "web", "svc", "reverse", "infrastructure"]
    tool: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    resource: ScopeResource


class _AccessCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID
    operation_uuid: UUID

    @field_validator("project_uuid", "operation_uuid")
    @classmethod
    def uuid_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("trusted scope and operation require UUIDv4")
        return value


class OpenSessionCommand(_AccessCommand):
    elevation_policy: Literal["fixed", "requestable"] = "requestable"
    label: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def safe_label(self) -> OpenSessionCommand:
        if self.label is not None and (
            not 1 <= len(self.label.strip()) <= 128
            or self.label != self.label.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in self.label)
        ):
            raise ValueError("AgentSession label must be canonical and readable")
        return self


class RequestElevationCommand(_AccessCommand):
    agent_session_uuid: UUID
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    operations: tuple[str, ...] = Field(min_length=1, max_length=32)
    resources: tuple[ScopeEffect, ...] = Field(default=(), max_length=32)
    seconds: int = Field(strict=True, ge=1, le=_MAX_LIFETIME_SECONDS)

    @model_validator(mode="after")
    def exact_scope(self) -> RequestElevationCommand:
        if self.agent_session_uuid.version != 4:
            raise ValueError("AgentSession requires UUIDv4")
        if (
            len(set(self.operations)) != len(self.operations)
            or not set(self.operations) <= _OPERATIONS
        ):
            raise ValueError("unsafe operation list")
        normalized = normalized_resource_grants(
            [item.model_dump(mode="json") for item in self.resources],
            allowed_actions=set(self.operations),
            project_uuid=self.project_uuid,
        )
        # Do not create a misleading action-only elevated grant that no
        # V2 Hand can actually enforce against an exact owned resource.
        # Every elevated operation must be represented by >=1 exact scope.
        if {scope["action"] for scope in normalized} != set(self.operations):
            raise ValueError("every elevated Hand action needs a resource scope")
        return self


class ResolveElevationCommand(_AccessCommand):
    approval_uuid: UUID
    expected_approval_version: int = Field(strict=True, ge=1, le=2**63 - 1)
    approve: bool = Field(strict=True)
    allowed_operations: tuple[str, ...] | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def safe_subset(self) -> ResolveElevationCommand:
        if self.approval_uuid.version != 4:
            raise ValueError("approval requires UUIDv4")
        if self.allowed_operations is not None and (
            len(set(self.allowed_operations)) != len(self.allowed_operations)
            or not set(self.allowed_operations) <= _OPERATIONS
        ):
            raise ValueError("invalid approval operation subset")
        return self


class RevokeSessionCommand(_AccessCommand):
    agent_session_uuid: UUID
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)

    @field_validator("agent_session_uuid")
    @classmethod
    def session_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("AgentSession requires UUIDv4")
        return value


@dataclass(frozen=True, slots=True)
class VerifiedAccessCommandActor:
    actor_uuid: UUID
    project_uuid: UUID
    operation_uuid: UUID
    action: Literal[
        "session.open", "session.request_elevation", "session.resolve_elevation", "session.revoke"
    ]
    can_use_resources: bool
    can_approve: bool
    identity_authority: Literal["rauthy"]
    service_audience: Literal["briareus:access"]
    expires_at: datetime


class TrustedAccessCommandAttestor(Protocol):
    async def verify(
        self, request: object, command: _AccessCommand, action: str
    ) -> VerifiedAccessCommandActor:
        """Independently verify signed Rauthy subject, Platform, private peer.

        Request is an authenticated transport handle, NOT user-provided identity.
        """
        ...


class AccessRauthyCommandService:
    """Idempotent owner-local Access mutations, no management-plane dependency."""

    def __init__(
        self,
        *,
        database: PlatformDatabase,
        idempotency: IdempotentCommandExecutor,
        attestor: TrustedAccessCommandAttestor,
        resource_owner: TrustedResourceOwnerPort | None = None,
    ) -> None:
        if (
            database.engine.url.database != "briareus_access"
            or idempotency.database is not database
            or attestor is None
        ):
            raise ValueError("Authorization commands need one trusted Access owner and attestor")
        self._db = database
        self._idempotency = idempotency
        self._attestor = attestor
        self._resource_owner = resource_owner

    @staticmethod
    def _active_proof(
        verified: VerifiedAccessCommandActor,
        *,
        command: _AccessCommand,
        action: str,
        elevated: bool,
    ) -> None:
        now = datetime.now(UTC)
        if (
            not isinstance(verified, VerifiedAccessCommandActor)
            or not isinstance(verified.actor_uuid, UUID)
            or verified.actor_uuid.version != 4
            or verified.project_uuid != command.project_uuid
            or verified.operation_uuid != command.operation_uuid
            or verified.action != action
            or verified.identity_authority != "rauthy"
            or verified.service_audience != "briareus:access"
            or type(verified.can_use_resources) is not bool
            or type(verified.can_approve) is not bool
            or (not verified.can_approve if elevated else not verified.can_use_resources)
            or not isinstance(verified.expires_at, datetime)
            or verified.expires_at.tzinfo is None
            or not now < verified.expires_at <= now + timedelta(seconds=30)
        ):
            raise AccessDenied("current signed Rauthy/Platform operator scope required")

    async def _caller(
        self,
        request: object,
        command: _AccessCommand,
        action: str,
        *,
        elevated: bool,
    ) -> VerifiedAccessCommandActor:
        try:
            verified = await self._attestor.verify(request, command, action)
        except Exception:
            raise AccessDenied("trusted peer/Platform User unavailable") from None
        self._active_proof(verified, command=command, action=action, elevated=elevated)
        return verified

    @staticmethod
    def _audit(
        tx: AsyncSession,
        *,
        actor: UUID,
        project: UUID,
        operation: UUID,
        action: str,
        target: UUID,
    ) -> None:
        tx.add(
            SecurityAuditRow(
                actor_id=actor,
                project_id=project,
                action=action,
                object_id=str(target),
                details={"operation_uuid": str(operation)},
            )
        )
        tx.add(
            OutboxRow(
                event_name=action,
                event_payload={
                    "operation_uuid": str(operation),
                    "project_id": str(project),
                    "entity_id": str(target),
                },
            )
        )

    async def open_normal(self, request: object, command: OpenSessionCommand) -> CommandOutcome:
        action = "session.open"
        actor = await self._caller(request, command, action, elevated=False)

        async def reauthorize(_tx: AsyncSession) -> None:
            self._active_proof(actor, command=command, action=action, elevated=False)

        async def perform(tx: AsyncSession) -> CommandOutcome:
            self._active_proof(actor, command=command, action=action, elevated=False)
            from uuid import uuid4

            now = datetime.now(UTC)
            session_uuid = uuid4()
            operations = ["files.read", "project.metadata.read"]
            row = ProjectAgentSessionRow(
                session_uuid=session_uuid,
                project_id=command.project_uuid,
                created_by_principal_id=actor.actor_uuid,
                is_elevated=False,
                elevation_policy=command.elevation_policy,
                label=command.label,
                grants={"operations": operations, "resources": []},
                status="active",
                version=1,
                created_at=now,
                hard_expires_at=now + timedelta(hours=24),
            )
            tx.add(row)
            self._audit(
                tx,
                actor=actor.actor_uuid,
                project=command.project_uuid,
                operation=command.operation_uuid,
                action="session.opened",
                target=session_uuid,
            )
            return CommandOutcome(
                201,
                {
                    "session_uuid": str(row.session_uuid),
                    "project_uuid": str(row.project_id),
                    "revision": 1,
                    "status": "active",
                    "is_elevated": False,
                    "elevation_policy": row.elevation_policy,
                    "hard_expires_at": row.hard_expires_at.isoformat(),
                    "operations": operations,
                    "resources": [],
                },
            )

        return await self._idempotency.execute(
            actor_scope=str(actor.actor_uuid),
            project_scope=str(command.project_uuid),
            operation=action,
            key=str(command.operation_uuid),
            payload=command.model_dump(mode="json"),
            command=perform,
            reauthorize=reauthorize,
        )

    async def request_elevation(
        self, request: object, command: RequestElevationCommand
    ) -> CommandOutcome:
        action = "session.request_elevation"
        actor = await self._caller(request, command, action, elevated=False)
        resources = normalized_resource_grants(
            [item.model_dump(mode="json") for item in command.resources],
            allowed_actions=set(command.operations),
            project_uuid=command.project_uuid,
        )

        async def reauthorize(_tx: AsyncSession) -> None:
            self._active_proof(actor, command=command, action=action, elevated=False)

        async def perform(tx: AsyncSession) -> CommandOutcome:
            row = await tx.scalar(
                select(ProjectAgentSessionRow)
                .where(ProjectAgentSessionRow.session_uuid == command.agent_session_uuid)
                .with_for_update()
            )
            # Recheck after waiting for the Access row lock.
            self._active_proof(actor, command=command, action=action, elevated=False)
            now = datetime.now(UTC)
            if row is None or row.project_id != command.project_uuid:
                raise AccessDenied("unknown Project AgentSession")
            if row.created_by_principal_id != actor.actor_uuid:
                raise AccessDenied("an actor can request elevation only for own AgentSession")
            if row.version != command.expected_grant_revision:
                raise Conflict("stale AgentSession revision")
            if (
                row.status != "active"
                or row.hard_expires_at <= now
                or row.elevation_policy != "requestable"
                or row.is_elevated
            ):
                raise AccessDenied("AgentSession is not requestable and active")
            approval = SessionApprovalRow(
                id=command.operation_uuid,
                session_uuid=row.session_uuid,
                project_id=row.project_id,
                requested_by_user_id=actor.actor_uuid,
                requested_grants={"operations": sorted(command.operations), "resources": resources},
                requested_expires_at=now + timedelta(seconds=command.seconds),
                status="pending",
                version=1,
            )
            tx.add(approval)
            self._audit(
                tx,
                actor=actor.actor_uuid,
                project=command.project_uuid,
                operation=command.operation_uuid,
                action="session.elevation_requested",
                target=approval.id,
            )
            return CommandOutcome(
                202,
                {
                    "id": str(approval.id),
                    "project_uuid": str(approval.project_id),
                    "agent_session_uuid": str(approval.session_uuid),
                    "requested_by_user_uuid": str(approval.requested_by_user_id),
                    "status": "pending",
                    "version": 1,
                    "requested_operations": sorted(command.operations),
                    "requested_resources": resources,
                    "requested_expires_at": approval.requested_expires_at.isoformat(),
                    "resolved_by_user_uuid": None,
                    "issued_session_uuid": None,
                },
            )

        return await self._idempotency.execute(
            actor_scope=str(actor.actor_uuid),
            project_scope=str(command.project_uuid),
            operation=action,
            key=str(command.operation_uuid),
            payload=command.model_dump(mode="json"),
            command=perform,
            reauthorize=reauthorize,
        )

    async def resolve_elevation(
        self, request: object, command: ResolveElevationCommand
    ) -> CommandOutcome:
        action = "session.resolve_elevation"
        actor = await self._caller(request, command, action, elevated=True)

        async def reauthorize(_tx: AsyncSession) -> None:
            self._active_proof(actor, command=command, action=action, elevated=True)

        async def perform(tx: AsyncSession) -> CommandOutcome:
            # Resolve and base revoke must take row locks in the same order:
            # base AgentSession FIRST, approval SECOND. Otherwise concurrent
            # approval vs. parent revocation can deadlock. An unlocked lookup
            # only discovers the immutable base reference; the locked re-read
            # below remains the authority for all mutable approval fields.
            initial = await tx.scalar(
                select(SessionApprovalRow).where(SessionApprovalRow.id == command.approval_uuid)
            )
            if initial is None or initial.project_id != command.project_uuid:
                raise AccessDenied("approval Project mismatch")
            base = await tx.scalar(
                select(ProjectAgentSessionRow)
                .where(ProjectAgentSessionRow.session_uuid == initial.session_uuid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            approval = await tx.scalar(
                select(SessionApprovalRow)
                .where(SessionApprovalRow.id == command.approval_uuid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            # Row lock waits must not extend a once-valid approver proof.
            self._active_proof(actor, command=command, action=action, elevated=True)
            if (
                approval is None
                or approval.project_id != command.project_uuid
                or approval.session_uuid != initial.session_uuid
            ):
                raise AccessDenied("approval Project/AgentSession changed")
            if (
                approval.version != command.expected_approval_version
                or approval.status != "pending"
            ):
                raise Conflict("approval revision or state changed")
            if approval.requested_by_user_id == actor.actor_uuid:
                raise AccessDenied("an elevation requester cannot resolve own request")
            now = datetime.now(UTC)
            if (
                base is None
                or base.project_id != command.project_uuid
                or base.status != "active"
                or base.hard_expires_at <= now
                or base.is_elevated
                or base.elevation_policy != "requestable"
                or base.created_by_principal_id != approval.requested_by_user_id
            ):
                raise AccessDenied("base AgentSession no longer eligible")
            if command.approve and approval.requested_expires_at <= now:
                raise Conflict("pending approval lifetime expired")
            operations = approval.requested_grants.get("operations")
            if (
                not isinstance(operations, list)
                or not operations
                or any(not isinstance(value, str) for value in operations)
                or len(set(operations)) != len(operations)
                or not set(operations) <= _OPERATIONS
            ):
                raise AccessDenied("invalid stored operation request")
            allowed = (
                sorted(command.allowed_operations)
                if command.allowed_operations is not None
                else sorted(operations)
            )
            if command.approve and (not allowed or not set(allowed) <= set(operations)):
                raise AccessDenied("approval may not expand original request")
            try:
                scopes = normalized_resource_grants(
                    approval.requested_grants.get("resources", []),
                    allowed_actions=set(operations),
                    project_uuid=command.project_uuid,
                )
            except ValueError:
                raise AccessDenied("stored Resource scope invalid") from None
            granted = [item for item in scopes if item["action"] in allowed]
            issued: UUID | None = None
            if command.approve:
                if {scope["action"] for scope in granted} != set(allowed):
                    raise AccessDenied("every approved effect requires an owned resource scope")
                if granted:
                    if self._resource_owner is None:
                        raise AccessDenied("current Resource owner proof unavailable")
                    for item in granted:
                        owner_proof = self._resource_owner.verify_current_scope(
                            project_uuid=command.project_uuid, scope=item
                        )
                        if not matches_current_owner(
                            owner_proof, project_uuid=command.project_uuid, scope=item
                        ):
                            raise AccessDenied("resource does not belong to current Project")
                from uuid import uuid4

                issued = uuid4()
                # An elevated child may never outlive its base session.
                expiry = min(
                    approval.requested_expires_at,
                    base.hard_expires_at,
                    now + timedelta(seconds=_MAX_LIFETIME_SECONDS),
                )
                if expiry <= now:
                    raise Conflict("approval TTL exhausted")
                tx.add(
                    ProjectAgentSessionRow(
                        session_uuid=issued,
                        project_id=base.project_id,
                        created_by_principal_id=approval.requested_by_user_id,
                        is_elevated=True,
                        elevation_policy="fixed",
                        label=base.label,
                        grants={"operations": allowed, "resources": granted},
                        status="active",
                        version=1,
                        created_at=now,
                        hard_expires_at=expiry,
                    )
                )
            approval.status = "approved" if command.approve else "rejected"
            approval.version += 1
            approval.resolved_by_user_id = actor.actor_uuid
            approval.resolved_at = now
            approval.issued_session_uuid = issued
            self._audit(
                tx,
                actor=actor.actor_uuid,
                project=command.project_uuid,
                operation=command.operation_uuid,
                action="session.elevation_resolved",
                target=approval.id,
            )
            return CommandOutcome(
                200,
                {
                    "id": str(approval.id),
                    "project_uuid": str(approval.project_id),
                    "agent_session_uuid": str(approval.session_uuid),
                    "requested_by_user_uuid": str(approval.requested_by_user_id),
                    "status": approval.status,
                    "version": approval.version,
                    "requested_operations": operations,
                    "requested_resources": scopes,
                    "requested_expires_at": approval.requested_expires_at.isoformat(),
                    "resolved_by_user_uuid": str(actor.actor_uuid),
                    "issued_session_uuid": str(issued) if issued else None,
                },
            )

        return await self._idempotency.execute(
            actor_scope=str(actor.actor_uuid),
            project_scope=str(command.project_uuid),
            operation=action,
            key=str(command.operation_uuid),
            payload=command.model_dump(mode="json"),
            command=perform,
            reauthorize=reauthorize,
        )

    async def revoke_session(
        self, request: object, command: RevokeSessionCommand
    ) -> CommandOutcome:
        action = "session.revoke"
        actor = await self._caller(request, command, action, elevated=True)

        async def reauthorize(_tx: AsyncSession) -> None:
            self._active_proof(actor, command=command, action=action, elevated=True)

        async def perform(tx: AsyncSession) -> CommandOutcome:
            row = await tx.scalar(
                select(ProjectAgentSessionRow)
                .where(ProjectAgentSessionRow.session_uuid == command.agent_session_uuid)
                .with_for_update()
            )
            self._active_proof(actor, command=command, action=action, elevated=True)
            if row is None or row.project_id != command.project_uuid:
                raise AccessDenied("unknown Project AgentSession")
            if row.version != command.expected_grant_revision:
                raise Conflict("AgentSession revision changed")
            if row.status != "active":
                raise Conflict("AgentSession already revoked")
            now = datetime.now(UTC)
            # Atomic transitive revoke: an approved elevated AgentSession
            # must not remain usable after revocation of its base. The
            # approval row is the reviewed durable parent→child mapping;
            # do not rely on Valkey TTL or delayed event delivery.
            if not row.is_elevated:
                issued = list(
                    await tx.scalars(
                        select(SessionApprovalRow.issued_session_uuid)
                        .where(
                            SessionApprovalRow.session_uuid == row.session_uuid,
                            SessionApprovalRow.project_id == row.project_id,
                            SessionApprovalRow.issued_session_uuid.is_not(None),
                        )
                        .with_for_update()
                    )
                )
                if len(set(issued)) != len(issued):
                    raise AccessDenied("duplicate elevated AgentSession reference")
                for child_id in issued:
                    if not isinstance(child_id, UUID) or child_id.version != 4:
                        raise AccessDenied("invalid elevated AgentSession reference")
                    child = await tx.scalar(
                        select(ProjectAgentSessionRow)
                        .where(ProjectAgentSessionRow.session_uuid == child_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if (
                        child is None
                        or child.project_id != row.project_id
                        or child.created_by_principal_id != row.created_by_principal_id
                        or child.is_elevated is not True
                    ):
                        raise AccessDenied("inconsistent elevated AgentSession ownership")
                    self._active_proof(actor, command=command, action=action, elevated=True)
                    if child.status == "active":
                        child.status = "revoked"
                        child.revoked_at = now
                        child.version += 1
                        self._audit(
                            tx,
                            actor=actor.actor_uuid,
                            project=command.project_uuid,
                            operation=command.operation_uuid,
                            action="session.revoked_by_parent",
                            target=child.session_uuid,
                        )
                    elif child.status != "revoked":
                        raise AccessDenied("elevated session state cannot be safely revoked")
            self._active_proof(actor, command=command, action=action, elevated=True)
            row.status = "revoked"
            row.revoked_at = now
            row.version += 1
            self._audit(
                tx,
                actor=actor.actor_uuid,
                project=command.project_uuid,
                operation=command.operation_uuid,
                action="session.revoked",
                target=row.session_uuid,
            )
            return CommandOutcome(
                200,
                {
                    "session_uuid": str(row.session_uuid),
                    "project_uuid": str(row.project_id),
                    "status": "revoked",
                    "revision": row.version,
                },
            )

        return await self._idempotency.execute(
            actor_scope=str(actor.actor_uuid),
            project_scope=str(command.project_uuid),
            operation=action,
            key=str(command.operation_uuid),
            payload=command.model_dump(mode="json"),
            command=perform,
            reauthorize=reauthorize,
        )
