# ruff: noqa: B008  # FastAPI injected Depends
"""Private draft Admin projections. No legacy/public mount."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from authorization._platform_application import PlatformApplication
from authorization._platform_permissions import project_permit, team_permit
from authorization._project_access import CallerPrincipal
from authorization._project_sessions import (
    ELEVATED_HARD_TTL,
    NORMAL_TTL,
    SAFE_BASIC_GRANTS,
    SUPPORTED_GRANTS,
)
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from common.platform_errors import AccessDenied
from common.platform_ids import PlatformProjectId, TeamId
from identity._domain import UserRole
from identity._persistence import InvitationRow, UserRow
from projects._persistence import ProjectRow
from teams._persistence import TeamRow


class View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeamActions(View):
    team_id: UUID
    decision_version: str
    can_manage_resources: bool
    can_manage_members: bool
    can_transfer_team: bool


class ProjectActions(View):
    project_id: UUID
    owner_scope: str
    owner_id: UUID
    decision_version: str
    permissions: list[str]
    can_manage_project_resources: bool
    can_approve_agent_sessions: bool
    can_manage_agents: bool
    can_transfer_project: bool
    can_manage_team_members: bool
    can_manage_team_resources: bool


class MemberDisplay(View):
    team_id: UUID
    user_id: UUID
    username: str
    enabled: bool
    active: bool


class UserDisplay(View):
    user_id: UUID
    username: str
    enabled: bool
    role: str
    credential_version: int
    # Server-computed UI hints, NOT bearer/authoritative mutation permits.
    allowed_actions: list[str] = Field(default_factory=list)


class InvitationDisplay(View):
    invitation_id: UUID
    kind: str
    created_at: datetime
    expires_at: datetime | None
    used_at: datetime | None
    revoked_at: datetime | None
    issuer_id: UUID | None
    target_user_id: UUID | None


class SessionDisplay(View):
    label: str | None
    session_uuid: UUID
    project_id: UUID
    status: str
    grants: list[str]
    is_elevated: bool
    elevation_policy: str
    hard_expires_at: datetime
    created_at: datetime
    version: int


class ApprovalDisplay(View):
    version: int
    request_id: UUID
    session_uuid: UUID
    project_id: UUID
    status: str
    requested_grants: list[str]
    requested_expires_at: datetime
    issued_session_uuid: UUID | None
    requested_by_user_id: UUID
    resolved_by_user_id: UUID | None
    resolved_at: datetime | None


class GrantCatalog(View):
    normal_hard_ttl_seconds: int
    elevated_max_seconds: int
    basic_grants: list[str]
    supported_grants: list[str]


class MeContext(View):
    user: UserDisplay
    teams: list[TeamActions]
    projects: list[ProjectActions]
    global_operator: bool


class OperatorSummary(View):
    users: int
    teams: int
    projects: int
    agent_sessions: int


Caller = Callable[..., Awaitable[CallerPrincipal]]


def user_allowed_actions(
    row: UserRow,
    *,
    active_admin_count: int,
    owned_teams: set[UUID],
    owned_projects: set[UUID],
) -> list[str]:
    """UI projection only. Every mutation independently rechecks SQL rights."""
    protected_admin = row.role == "superuser" and row.enabled and active_admin_count <= 1
    actions: list[str] = []
    if row.enabled:
        actions.append("identity.password_reset.issue")
        if not protected_admin:
            actions.append("identity.suspend")
    else:
        actions.append("identity.restore")
    if row.role == "superuser":
        if not protected_admin:
            actions.append("identity.superuser.demote")
    elif row.enabled:
        actions.append("identity.superuser.promote")
    if not protected_admin and row.id not in owned_teams and row.id not in owned_projects:
        actions.append("identity.delete")
    return actions


def _grants(raw: object) -> list[str]:
    if not isinstance(raw, dict) or not isinstance(raw.get("operations"), list):
        return []
    return [v for v in raw["operations"] if isinstance(v, str)]


def build_unmounted_overview_router(
    application: PlatformApplication,
    caller: Caller,
) -> APIRouter:
    router = APIRouter(tags=["platform-overview-draft"])

    @router.get("/me/context", response_model=MeContext)
    async def current_context(
        subject: CallerPrincipal = Depends(caller),
    ) -> MeContext:
        async with application.db.transaction() as tx:
            user = await application.current_user(tx, subject)
            teams = await application.visible_teams(tx, subject)
            projects = await application.visible_projects(tx, subject)
            team_actions = []
            for team in teams:
                permit = await team_permit(tx, application, subject, team.id)
                team_actions.append(
                    TeamActions(
                        team_id=team.id,
                        decision_version=permit.decision_version,
                        can_manage_resources=permit.can_manage_resources,
                        can_manage_members=permit.can_manage_members,
                        can_transfer_team=permit.can_transfer_team,
                    )
                )
            project_actions = []
            for project in projects:
                project_decision = await project_permit(tx, application, subject, project.id)
                project_actions.append(
                    ProjectActions(
                        project_id=project.id,
                        owner_scope=project_decision.owner_scope,
                        owner_id=project_decision.owner_id,
                        decision_version=project_decision.decision_version,
                        permissions=["use_resources", "approve_agent_session"],
                        can_manage_project_resources=project_decision.can_manage_project_resources,
                        can_approve_agent_sessions=project_decision.can_approve_agent_sessions,
                        can_manage_agents=project_decision.can_manage_agents,
                        can_transfer_project=project_decision.can_transfer_project,
                        can_manage_team_members=project_decision.can_manage_team_members,
                        can_manage_team_resources=project_decision.can_manage_team_resources,
                    )
                )
            return MeContext(
                user=UserDisplay(
                    user_id=user.id,
                    username=user.username,
                    enabled=user.enabled,
                    role=user.role.value,
                    credential_version=user.credential_version,
                    allowed_actions=[
                        "identity.password.change",
                        "auth.logout",
                        "auth.refresh",
                    ]
                    + (
                        ["operator.summary", "identity.users.list"]
                        if user.role is UserRole.SUPERUSER
                        else []
                    ),
                ),
                teams=team_actions,
                projects=project_actions,
                global_operator=user.role is UserRole.SUPERUSER,
            )

    @router.get("/users", response_model=list[UserDisplay])
    async def list_users(
        limit: int = Query(default=250, ge=1, le=250),
        subject: CallerPrincipal = Depends(caller),
    ) -> list[UserDisplay]:
        async with application.db.transaction() as tx:
            actor = await application.current_user(tx, subject)
            if actor.role is not UserRole.SUPERUSER:
                raise AccessDenied("superuser permission required")
            rows = list(
                await tx.scalars(
                    select(UserRow)
                    .where(UserRow.deleted_at.is_(None))
                    .order_by(UserRow.username, UserRow.id)
                    .limit(limit)
                )
            )
            ids = [row.id for row in rows]
            owned_teams = (
                set(
                    await tx.scalars(
                        select(TeamRow.owner_user_id).where(TeamRow.owner_user_id.in_(ids))
                    )
                )
                if ids
                else set()
            )
            owned_projects = (
                {
                    owner_id
                    for owner_id in await tx.scalars(
                        select(ProjectRow.owner_user_id).where(ProjectRow.owner_user_id.in_(ids))
                    )
                    if owner_id is not None
                }
                if ids
                else set()
            )
            active_admins = await tx.scalar(
                select(func.count(UserRow.id)).where(
                    UserRow.role == "superuser",
                    UserRow.enabled.is_(True),
                    UserRow.deleted_at.is_(None),
                )
            )
            active_admin_count = active_admins or 0
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="operator.users_read",
                target="users",
            )
            result: list[UserDisplay] = []
            for row in rows:
                actions = user_allowed_actions(
                    row,
                    active_admin_count=active_admin_count,
                    owned_teams=owned_teams,
                    owned_projects=owned_projects,
                )
                result.append(
                    UserDisplay(
                        user_id=row.id,
                        username=row.username,
                        enabled=row.enabled,
                        role=row.role,
                        credential_version=row.credential_version,
                        allowed_actions=actions,
                    )
                )
            return result

    @router.get("/teams/{team_id}/permissions", response_model=TeamActions)
    async def team_permissions(
        team_id: UUID,
        subject: CallerPrincipal = Depends(caller),
    ) -> TeamActions:
        async with application.db.transaction() as tx:
            decision = await team_permit(tx, application, subject, TeamId(team_id))
            return TeamActions(
                team_id=team_id,
                decision_version=decision.decision_version,
                can_manage_resources=decision.can_manage_resources,
                can_manage_members=decision.can_manage_members,
                can_transfer_team=decision.can_transfer_team,
            )

    @router.get("/projects/{project_id}/access", response_model=ProjectActions)
    async def project_access(
        project_id: UUID,
        subject: CallerPrincipal = Depends(caller),
    ) -> ProjectActions:
        async with application.db.transaction() as tx:
            decision = await project_permit(tx, application, subject, PlatformProjectId(project_id))
            return ProjectActions(
                project_id=project_id,
                owner_scope=decision.owner_scope,
                owner_id=decision.owner_id,
                decision_version=decision.decision_version,
                permissions=["use_resources", "approve_agent_session"],
                can_manage_project_resources=decision.can_manage_project_resources,
                can_approve_agent_sessions=decision.can_approve_agent_sessions,
                can_manage_agents=decision.can_manage_agents,
                can_transfer_project=decision.can_transfer_project,
                can_manage_team_members=decision.can_manage_team_members,
                can_manage_team_resources=decision.can_manage_team_resources,
            )

    @router.get("/teams/{team_id}/member-details", response_model=list[MemberDisplay])
    async def team_member_details(
        team_id: UUID,
        subject: CallerPrincipal = Depends(caller),
    ) -> list[MemberDisplay]:
        from teams._persistence import TeamMembershipRow

        async with application.db.transaction() as tx:
            await team_permit(tx, application, subject, TeamId(team_id))
            rows = await tx.execute(
                select(TeamMembershipRow, UserRow)
                .join(UserRow, UserRow.id == TeamMembershipRow.user_id)
                .where(TeamMembershipRow.team_id == team_id)
                .order_by(UserRow.username, UserRow.id)
            )
            return [
                MemberDisplay(
                    team_id=team_id,
                    user_id=user.id,
                    username=user.username,
                    enabled=user.enabled,
                    active=member.active,
                )
                for member, user in rows.all()
                if user.deleted_at is None
            ]

    @router.get("/invitations", response_model=list[InvitationDisplay])
    async def list_invitations(
        subject: CallerPrincipal = Depends(caller),
    ) -> list[InvitationDisplay]:
        async with application.db.transaction() as tx:
            actor = await application.current_user(tx, subject)
            query = (
                select(InvitationRow)
                .order_by(InvitationRow.created_at.desc(), InvitationRow.id)
                .limit(250)
            )
            if actor.role is not UserRole.SUPERUSER:
                query = query.where(InvitationRow.created_by_user_id == subject.user_id)
            records = await tx.scalars(query)
            return [
                InvitationDisplay(
                    invitation_id=row.id,
                    kind=row.kind,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                    used_at=row.used_at,
                    revoked_at=row.revoked_at,
                    issuer_id=row.created_by_user_id,
                    target_user_id=row.target_user_id,
                )
                for row in records
            ]

    @router.get("/projects/{project_id}/sessions", response_model=list[SessionDisplay])
    async def list_sessions(
        project_id: UUID,
        subject: CallerPrincipal = Depends(caller),
    ) -> list[SessionDisplay]:
        pid = PlatformProjectId(project_id)
        async with application.db.transaction() as tx:
            await application.project_allowed(tx, subject, pid)
            records = await tx.scalars(
                select(ProjectAgentSessionRow)
                .where(ProjectAgentSessionRow.project_id == pid)
                .order_by(
                    ProjectAgentSessionRow.created_at.desc(),
                    ProjectAgentSessionRow.session_uuid,
                )
                .limit(250)
            )
            return [
                SessionDisplay(
                    label=row.label,
                    session_uuid=row.session_uuid,
                    project_id=row.project_id,
                    status=row.status,
                    grants=_grants(row.grants),
                    is_elevated=row.is_elevated,
                    elevation_policy=row.elevation_policy,
                    hard_expires_at=row.hard_expires_at,
                    created_at=row.created_at,
                    version=row.version,
                )
                for row in records
            ]

    @router.get("/projects/{project_id}/approvals", response_model=list[ApprovalDisplay])
    async def list_approvals(
        project_id: UUID,
        subject: CallerPrincipal = Depends(caller),
    ) -> list[ApprovalDisplay]:
        pid = PlatformProjectId(project_id)
        async with application.db.transaction() as tx:
            await application.project_allowed(tx, subject, pid)
            records = await tx.scalars(
                select(SessionApprovalRow)
                .where(SessionApprovalRow.project_id == pid)
                .order_by(SessionApprovalRow.created_at.desc(), SessionApprovalRow.id)
                .limit(250)
            )
            return [
                ApprovalDisplay(
                    version=row.version,
                    request_id=row.id,
                    session_uuid=row.session_uuid,
                    project_id=row.project_id,
                    status=row.status,
                    requested_grants=_grants(row.requested_grants),
                    requested_expires_at=row.requested_expires_at,
                    issued_session_uuid=row.issued_session_uuid,
                    requested_by_user_id=row.requested_by_user_id,
                    resolved_by_user_id=row.resolved_by_user_id,
                    resolved_at=row.resolved_at,
                )
                for row in records
            ]

    @router.get("/projects/{project_id}/grants-catalog", response_model=GrantCatalog)
    async def grants_catalog(
        project_id: UUID,
        subject: CallerPrincipal = Depends(caller),
    ) -> GrantCatalog:
        async with application.db.transaction() as tx:
            await application.project_allowed(tx, subject, PlatformProjectId(project_id))
            return GrantCatalog(
                normal_hard_ttl_seconds=int(NORMAL_TTL.total_seconds()),
                elevated_max_seconds=int(ELEVATED_HARD_TTL.total_seconds()),
                basic_grants=sorted(SAFE_BASIC_GRANTS),
                supported_grants=sorted(SUPPORTED_GRANTS),
            )

    @router.get("/operator/summary", response_model=OperatorSummary)
    async def operator_summary(
        subject: CallerPrincipal = Depends(caller),
    ) -> OperatorSummary:
        async with application.db.transaction() as tx:
            actor = await application.current_user(tx, subject)
            if actor.role is not UserRole.SUPERUSER:
                raise AccessDenied("superuser permission required")
            from projects._persistence import ProjectRow
            from teams._persistence import TeamRow

            users = await tx.scalar(
                select(func.count()).select_from(UserRow).where(UserRow.deleted_at.is_(None))
            )
            teams = await tx.scalar(select(func.count()).select_from(TeamRow))
            projects = await tx.scalar(select(func.count()).select_from(ProjectRow))
            active = await tx.scalar(
                select(func.count())
                .select_from(ProjectAgentSessionRow)
                .where(
                    ProjectAgentSessionRow.status == "active",
                )
            )
            application._audit(
                tx,
                actor=subject.user_id,
                project=None,
                action="operator.summary_read",
                target="operator",
            )
            return OperatorSummary(
                users=users or 0,
                teams=teams or 0,
                projects=projects or 0,
                agent_sessions=active or 0,
            )

    return router
