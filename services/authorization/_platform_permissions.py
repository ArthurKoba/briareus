"""Server-computed Project/Team permission projections, never bearer tokens."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_errors import AccessDenied
from common.platform_ids import PlatformProjectId, TeamId, UserId
from identity._domain import UserRole
from teams._persistence import TeamMembershipRow

from ._platform_application import PlatformApplication
from ._project_access import CallerPrincipal


@dataclass(frozen=True, slots=True)
class ProjectPermit:
    project_id: PlatformProjectId
    caller_user_id: UserId
    decision_version: str
    owner_scope: str
    owner_id: UUID
    can_use_resources: bool
    can_manage_project_resources: bool
    can_approve_agent_sessions: bool
    can_manage_agents: bool
    can_transfer_project: bool
    can_manage_team_members: bool
    can_manage_team_resources: bool


@dataclass(frozen=True, slots=True)
class TeamPermit:
    team_id: TeamId
    caller_user_id: UserId
    decision_version: str
    can_manage_resources: bool
    can_manage_members: bool
    can_transfer_team: bool


def _revision(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


async def project_permit(
    tx: AsyncSession,
    app: PlatformApplication,
    caller: CallerPrincipal,
    project_id: PlatformProjectId,
) -> ProjectPermit:
    user = await app.current_user(tx, caller)
    await app.project_allowed(tx, caller, project_id)
    project = await app.projects.get(tx, project_id)
    if project is None:
        raise AccessDenied("Project access denied")
    admin = user.role is UserRole.SUPERUSER
    parts = (
        "project-access-v1",
        str(caller.user_id),
        str(user.credential_version),
        user.role.value,
        str(project.id),
        str(project.version),
        str(project.resource_revision),
    )
    if project.owner_team_id is None:
        if project.owner_user_id is None:
            raise AccessDenied("Project owner unavailable")
        managing = admin or project.owner_user_id == caller.user_id
        return ProjectPermit(
            project_id,
            caller.user_id,
            _revision((*parts, "personal", str(project.owner_user_id))),
            "project",
            project.id,
            True,
            True,
            True,
            True,
            managing,
            False,
            False,
        )

    tid = TeamId(project.owner_team_id)
    team = await app.teams.get(tx, tid)
    if team is None:
        raise AccessDenied("Team unavailable")
    membership = await tx.scalar(
        select(TeamMembershipRow).where(
            TeamMembershipRow.team_id == tid,
            TeamMembershipRow.user_id == caller.user_id,
            TeamMembershipRow.active.is_(True),
        )
    )
    if membership is None and not admin:
        raise AccessDenied("Team membership required")
    managing = admin or team.owner_user_id == caller.user_id
    revision = _revision(
        (
            *parts,
            "team",
            str(team.id),
            str(team.version),
            str(team.resource_revision),
            str(membership.version) if membership is not None else "superuser",
        )
    )
    return ProjectPermit(
        project_id,
        caller.user_id,
        revision,
        "team",
        team.id,
        True,
        True,
        True,
        True,
        managing,
        managing,
        True,
    )


async def team_permit(
    tx: AsyncSession,
    app: PlatformApplication,
    caller: CallerPrincipal,
    team_id: TeamId,
) -> TeamPermit:
    user = await app.current_user(tx, caller)
    team = await app.teams.get(tx, team_id)
    if team is None:
        raise AccessDenied("Team access denied")
    membership = await tx.scalar(
        select(TeamMembershipRow).where(
            TeamMembershipRow.team_id == team_id,
            TeamMembershipRow.user_id == caller.user_id,
            TeamMembershipRow.active.is_(True),
        )
    )
    admin = user.role is UserRole.SUPERUSER
    if membership is None and not admin:
        raise AccessDenied("Team access denied")
    managing = admin or team.owner_user_id == caller.user_id
    revision = _revision(
        (
            "team-access-v1",
            str(caller.user_id),
            str(user.credential_version),
            user.role.value,
            str(team.id),
            str(team.version),
            str(team.resource_revision),
            str(membership.version) if membership is not None else "superuser",
        )
    )
    return TeamPermit(team_id, caller.user_id, revision, True, managing, managing)
