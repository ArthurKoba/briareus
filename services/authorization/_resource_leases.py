"""Private credential-use port; no MCP/REST handler can fetch secret values.

Leases are stored as short-lived one-use DB rows without secret bytes.
Redemption always rechecks authenticated caller, Project, membership,
AgentSession grant/TTL, owner revisions and resource version against SQL.
A result SecretStr may only be passed to a trusted in-process provider adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_errors import AccessDenied, Conflict, InvalidInput
from common.platform_ids import AgentSessionUuid, PlatformProjectId, TeamId, UserId
from projects._resource_domain import ResourceKind, ResourceScope
from projects._resource_persistence import CredentialLeaseRow, IntegrationRow, VariableRow
from projects._resource_service import ResourceService, owner_of

from ._platform_application import PlatformApplication
from ._project_access import CallerPrincipal
from ._project_sessions import ProjectSessionService
from ._service_identity import (
    ACTION_AUDIENCES,
    CurrentServiceDecisionValidator,
    ServiceAuthorizationDecision,
)

LEASE_TTL = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class CredentialLease:
    """Non-secret internal handle. Do not serialize into external API output."""

    lease_id: UUID
    resource_id: UUID
    project_id: PlatformProjectId
    kind: ResourceKind
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CredentialOperationContext:
    actor_user_id: UserId
    project_id: PlatformProjectId
    session_uuid: AgentSessionUuid
    resource_id: UUID
    kind: ResourceKind


class CredentialProviderAdapter(Protocol):
    """Only approved backend adapters implement this private callback.

    Credential is not serializable to MCP/Admin UI/logs; adapters must
    return redacted results and never inject it into a generic process env.
    """

    async def execute(
        self,
        credential: SecretStr,
        context: CredentialOperationContext,
    ) -> None: ...


class ResourceCredentialUse:
    def __init__(
        self,
        application: PlatformApplication,
        resources: ResourceService,
        sessions: ProjectSessionService,
        validator: CurrentServiceDecisionValidator | None = None,
    ) -> None:
        self.application = application
        self.resources = resources
        self.sessions = sessions
        self.validator = validator

    @staticmethod
    def _grant(kind: ResourceKind) -> str:
        if kind is ResourceKind.INTEGRATION:
            return "integrations.use"
        if kind is ResourceKind.VARIABLE:
            return "variables.use"
        raise InvalidInput("unsupported credential resource kind")

    async def _verify_service_use(
        self,
        tx: AsyncSession,
        proof: ServiceAuthorizationDecision | None,
        *,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        session_uuid: AgentSessionUuid,
        resource_id: UUID | None,
        kind: ResourceKind,
    ) -> None:
        if self.validator is None:
            raise AccessDenied("C2 service identity validator is not configured")
        if (
            proof is None
            or resource_id is None
            or proof.actor_id != caller.user_id
            or proof.project_id != project_id
            or proof.session_uuid != session_uuid
            or proof.resource_id != resource_id
            or proof.operation != self._grant(kind)
            or proof.audience not in ACTION_AUDIENCES.get(proof.operation, frozenset())
        ):
            raise AccessDenied("credential use requires bound service audience and resource")
        await self.validator.verify_live_decision(tx, proof)

    async def acquire(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        session_uuid: AgentSessionUuid,
        *,
        kind: ResourceKind,
        resource_id: UUID | None = None,
        name: str | None = None,
        scope: ResourceScope = ResourceScope.ALL,
        service_proof: ServiceAuthorizationDecision | None = None,
        operation_uuid: UUID | None = None,
    ) -> CredentialLease:
        # A caller-provided UUID is neither a grant nor an authorization.
        # Stable service request identity prevents duplicate credential leases
        # under freshly signed JTI after an unknown network outcome.
        if service_proof is None or operation_uuid is None:
            raise AccessDenied("service-bound credential operation required")
        if (
            not isinstance(operation_uuid, UUID)
            or operation_uuid.version != 4
            or resource_id is None
            or name is not None
        ):
            raise AccessDenied("explicit credential resource/operation UUIDv4 required")
        await self._verify_service_use(
            tx,
            service_proof,
            caller=caller,
            project_id=project_id,
            session_uuid=session_uuid,
            resource_id=resource_id,
            kind=kind,
        )
        # The signed service validator has already locked and rechecked
        # User -> ServiceKey -> Project -> owning Team -> AgentSession.
        # Never obtain a Session lock BEFORE Project/Team ownership locks.
        owners = await self.resources._authorized_project_owners(
            tx, caller, project_id, scope, lock=True
        )
        candidate = await self.resources.resolve_for_project(
            tx,
            caller,
            project_id,
            kind,
            resource_id=resource_id,
            name=name,
            scope=scope,
        )
        if candidate.owner not in owners:
            raise AccessDenied("resource unavailable in current Project")
        row: IntegrationRow | VariableRow | None = (
            await self.resources.repository.integration(tx, candidate.resource_id, lock=True)
            if kind is ResourceKind.INTEGRATION
            else await self.resources.repository.variable(tx, candidate.resource_id, lock=True)
        )
        if row is None or row.version != candidate.version:
            raise AccessDenied("resource changed during selection")
        if kind is ResourceKind.VARIABLE and (
            not isinstance(row, VariableRow) or not row.is_secret
        ):
            raise InvalidInput("plain variables do not require a credential lease")

        project = await self.application.projects.get(tx, project_id, lock=True)
        if project is None:
            raise AccessDenied("Project access denied")
        session_view = await self.sessions.validate_operation(
            tx, caller, project_id, session_uuid, self._grant(kind)
        )
        team_version: int | None = None
        team_resource_revision: int | None = None
        if project.owner_team_id is not None:
            team = await self.application.teams.get(tx, TeamId(project.owner_team_id), lock=True)
            if team is None:
                raise AccessDenied("current Team unavailable")
            team_version = team.version
            team_resource_revision = team.resource_revision

        existing = await tx.scalar(
            select(CredentialLeaseRow.id).where(
                CredentialLeaseRow.project_id == project_id,
                CredentialLeaseRow.service_id == service_proof.service_id,
                CredentialLeaseRow.service_instance_uuid == service_proof.instance_uuid,
                CredentialLeaseRow.operation_uuid == operation_uuid,
            ).limit(1)
        )
        if existing is not None:
            raise Conflict("credential operation already issued; reconcile original lease")
        expires_at = datetime.now(UTC) + LEASE_TTL
        lease = CredentialLeaseRow(
            id=uuid4(),
            project_id=project_id,
            user_id=caller.user_id,
            session_uuid=session_uuid,
            resource_id=row.id,
            kind=kind.value,
            owner_scope=candidate.owner.scope.value,
            owner_id=candidate.owner.owner_id,
            resource_version=row.version,
            service_id=service_proof.service_id if service_proof is not None else None,
            service_instance_uuid=service_proof.instance_uuid,
            operation_uuid=operation_uuid,
            service_audience=service_proof.audience if service_proof is not None else None,
            correlation_id=service_proof.correlation_id if service_proof is not None else None,
            project_version=project.version,
            project_resource_revision=project.resource_revision,
            team_version=team_version,
            team_resource_revision=team_resource_revision,
            session_version=session_view.version,
            expires_at=expires_at,
        )
        tx.add(lease)
        await tx.flush()
        self.application._audit(
            tx,
            actor=caller.user_id,
            project=project_id,
            action="resource.credential_lease_issued",
            target=row.id,
            event={
                "lease_id": str(lease.id),
                "owner_scope": candidate.owner.scope.value,
                "owner_id": str(candidate.owner.owner_id),
                "kind": kind.value,
            },
        )
        return CredentialLease(
            lease_id=lease.id,
            resource_id=row.id,
            project_id=project_id,
            kind=kind,
            expires_at=expires_at,
        )

    async def redeem_for_trusted_adapter(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        session_uuid: AgentSessionUuid,
        handle: CredentialLease,
        *,
        service_proof: ServiceAuthorizationDecision | None = None,
    ) -> SecretStr:
        """Consume lease ONCE. No general REST/MCP response may call this port."""
        # Revalidate service identity BEFORE locking the resource lease row
        # to keep the User -> ServiceKey -> Project -> Team -> Session lock order.
        await self._verify_service_use(
            tx,
            service_proof,
            caller=caller,
            project_id=handle.project_id,
            session_uuid=session_uuid,
            resource_id=handle.resource_id,
            kind=handle.kind,
        )
        # Lock User -> Project -> Team before AgentSession; this ordering is
        # shared with Project resource mutation/owner-transfer operations.
        project = await self.resources._check_project(tx, caller, handle.project_id, lock=True)
        session_view = await self.sessions.validate_operation(
            tx, caller, handle.project_id, session_uuid, self._grant(handle.kind)
        )
        # Serialize redemption against concurrent revoke/approval mutation,
        # in addition to the checked session version and hard lease.
        active_session = await self.sessions._row(tx, session_uuid, lock=True)
        now = datetime.now(UTC)
        if active_session.status != "active" or active_session.hard_expires_at <= now:
            raise AccessDenied("SESSION_EXPIRED")
        row = cast(
            CredentialLeaseRow | None,
            await tx.scalar(
                select(CredentialLeaseRow)
                .where(CredentialLeaseRow.id == handle.lease_id)
                .with_for_update()
            ),
        )
        if (
            row is None
            or row.redeemed_at is not None
            or row.expires_at <= now
            or row.user_id != caller.user_id
            or row.session_uuid != session_uuid
            or row.project_id != handle.project_id
            or row.resource_id != handle.resource_id
            or row.kind != handle.kind.value
            or (service_proof is None and row.service_id is not None)
            or (
                service_proof is not None
                and (
                    row.service_id != service_proof.service_id
                    or row.service_instance_uuid != service_proof.instance_uuid
                    or row.service_audience != service_proof.audience
                    or row.correlation_id != service_proof.correlation_id
                )
            )
        ):
            raise AccessDenied("credential lease unavailable or expired")

        locked_grants: object = active_session.grants.get("operations")
        if (
            session_view.version != row.session_version
            or active_session.version != row.session_version
            or active_session.project_id != handle.project_id
            or not isinstance(locked_grants, list)
            or self._grant(handle.kind) not in locked_grants
        ):
            raise AccessDenied("AgentSession grant revision changed")

        # Project lock serializes transfer; Team lock serializes member revoke,
        # Team resource rotation, and source-owner change.
        if (
            project.version != row.project_version
            or project.resource_revision != row.project_resource_revision
        ):
            raise AccessDenied("Project authorization/resource revision changed")
        if project.owner_team_id is not None:
            team = await self.application.teams.get(tx, TeamId(project.owner_team_id), lock=True)
            if (
                team is None
                or team.version != row.team_version
                or team.resource_revision != row.team_resource_revision
            ):
                raise AccessDenied("Team authorization/resource revision changed")
        elif row.team_version is not None:
            raise AccessDenied("Project no longer inherits Team resources")

        resource: IntegrationRow | VariableRow | None
        if handle.kind is ResourceKind.INTEGRATION:
            resource = await self.resources.repository.integration(
                tx, handle.resource_id, lock=True
            )
        else:
            resource = await self.resources.repository.variable(tx, handle.resource_id, lock=True)
        if (
            resource is None
            or resource.version != row.resource_version
            or owner_of(resource).scope.value != row.owner_scope
            or owner_of(resource).owner_id != row.owner_id
        ):
            raise AccessDenied("resource revoked, moved, or rotated")
        if isinstance(resource, IntegrationRow):
            secret_value = resource.encrypted_credential
        else:
            if not resource.is_secret or resource.encrypted_value is None:
                raise AccessDenied("variable is no longer secret")
            secret_value = resource.encrypted_value

        row.redeemed_at = now
        self.application._audit(
            tx,
            actor=caller.user_id,
            project=handle.project_id,
            action="resource.credential_lease_redeemed",
            target=handle.resource_id,
            event={
                "lease_id": str(handle.lease_id),
                "owner_scope": row.owner_scope,
                "owner_id": str(row.owner_id),
            },
        )
        return self.resources._open_for_trusted_adapter(secret_value)

    async def execute_with_trusted_adapter(
        self,
        caller: CallerPrincipal,
        session_uuid: AgentSessionUuid,
        handle: CredentialLease,
        adapter: CredentialProviderAdapter,
        *,
        service_proof: ServiceAuthorizationDecision | None = None,
    ) -> None:
        """Commit single-use redemption BEFORE any provider-side execution.

        External result transport is intentionally absent until C1-B/C2
        approves the adapter and per-Project provenance/security contract.
        """
        async with self.application.db.transaction() as tx:
            credential = await self.redeem_for_trusted_adapter(
                tx, caller, session_uuid, handle, service_proof=service_proof
            )
        await adapter.execute(
            credential,
            CredentialOperationContext(
                actor_user_id=caller.user_id,
                project_id=handle.project_id,
                session_uuid=session_uuid,
                resource_id=handle.resource_id,
                kind=handle.kind,
            ),
        )
