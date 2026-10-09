"""Greenfield application composition: independent domain repositories, one UoW.

This module is intentionally not connected to historical OAuth/Admin runtimes
until C1-B/C2 approve caller credentials and revoke propagation. It never uses
client-provided Project IDs as proof of access.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents._domain import AgentIdentity
from agents._persistence import AgentIdentityRow
from agents._repository import AgentIdentityRepository, to_agent
from common.platform_db import PlatformDatabase
from common.platform_errors import (
    AccessDenied,
    AuthenticationRequired,
    Conflict,
    InvalidInput,
    ResourceMissing,
)
from common.platform_ids import AgentIdentityId, PlatformProjectId, TeamId, UserId
from identity._domain import User, UserRole
from identity._persistence import AdminTokenRevocationRow
from identity._repository import IdentityRepository, to_user
from projects._domain import Project
from projects._persistence import ProjectRow
from projects._policy import require_personal_owner
from projects._repository import ProjectRepository, to_project
from teams._domain import Team, TeamMembership
from teams._persistence import TeamMembershipRow, TeamRow
from teams._policy import require_team_owner
from teams._repository import TeamRepository, to_team

from ._platform_access import SqlMembership, SqlProjectOwnership, SqlUserAccess
from ._platform_persistence import OutboxRow, SecurityAuditRow
from ._project_access import (
    AuthenticationMethod,
    CallerPrincipal,
    ProjectAccessAuthorizer,
    ProjectPermission,
)


def _name(value: str) -> str:
    result = value.strip()
    if not (1 <= len(result) <= 255):
        raise InvalidInput("name must be 1-255 characters")
    return result


class PlatformApplication:
    """Use cases compose context-owned data adapters without a global Core service."""

    def __init__(self, database: PlatformDatabase) -> None:
        self.db = database
        self.users = IdentityRepository()
        self.teams = TeamRepository()
        self.projects = ProjectRepository()
        self.agents = AgentIdentityRepository()

    async def current_user(
        self, session: AsyncSession, caller: CallerPrincipal, *, lock: bool = False
    ) -> User:
        # Local Admin bearer actions are serialized with User suspension,
        # credential rotation and jti revocation. A stale in-flight HTTP
        # request cannot use a revoked token after the auth middleware returns.
        row = await self.users.get_user(session, caller.user_id, lock=lock)
        if row is None or not row.enabled or row.deleted_at is not None:
            if caller.authentication_method is AuthenticationMethod.LOCAL_LOGIN:
                raise AuthenticationRequired("local Admin credential is no longer active")
            raise AccessDenied("current user is unavailable")
        if caller.authentication_method is AuthenticationMethod.LOCAL_LOGIN:
            if (
                caller.credential_version is None
                or caller.admin_jti_digest is None
                or row.credential_version != caller.credential_version
            ):
                raise AuthenticationRequired("verified current local credential required")
            revoked = await session.scalar(
                select(AdminTokenRevocationRow.jti_digest).where(
                    AdminTokenRevocationRow.jti_digest == caller.admin_jti_digest
                )
            )
            if revoked is not None:
                raise AuthenticationRequired("Admin credential was revoked")
        return to_user(row)

    async def project_allowed(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        permission: ProjectPermission = ProjectPermission.USE_RESOURCES,
        *,
        for_write: bool = False,
    ) -> None:
        await self.current_user(session, caller, lock=for_write)
        authorized = ProjectAccessAuthorizer(
            users=SqlUserAccess(session, self.users),
            projects=SqlProjectOwnership(session, self.projects),
            memberships=SqlMembership(session, self.teams),
        )
        if not await authorized.allows(caller, project_id, permission):
            # One opaque denial for nonexistent and inaccessible projects.
            raise AccessDenied("Project access denied")

    @staticmethod
    def _audit(
        session: AsyncSession,
        *,
        actor: UserId | None,
        project: PlatformProjectId | None,
        action: str,
        target: UUID | str,
        event: dict[str, object] | None = None,
    ) -> None:
        details: dict[str, object] = event or {}
        session.add(
            SecurityAuditRow(
                id=uuid4(),
                actor_id=actor,
                project_id=project,
                action=action,
                object_id=str(target),
                details=details,
            )
        )
        session.add(
            OutboxRow(
                id=uuid4(),
                event_name=action,
                event_payload={
                    "actor_id": str(actor) if actor else None,
                    "project_id": str(project) if project else None,
                    "object_id": str(target),
                    "details": details,
                },
            )
        )

    async def create_team(
        self, session: AsyncSession, caller: CallerPrincipal, *, name: str
    ) -> Team:
        await self.current_user(session, caller, lock=True)
        row = TeamRow(id=uuid4(), name=_name(name), owner_user_id=caller.user_id, version=1)
        session.add(row)
        await session.flush()
        session.add(
            TeamMembershipRow(
                id=uuid4(),
                team_id=row.id,
                user_id=caller.user_id,
                active=True,
                version=1,
            )
        )
        self._audit(
            session,
            actor=caller.user_id,
            project=None,
            action="team.created",
            target=row.id,
        )
        return to_team(row)

    async def visible_teams(self, session: AsyncSession, caller: CallerPrincipal) -> list[Team]:
        user = await self.current_user(session, caller)
        if user.role is UserRole.SUPERUSER:
            self._audit(
                session,
                actor=caller.user_id,
                project=None,
                action="operator.teams_read",
                target="teams",
            )
            rows = await session.scalars(select(TeamRow).order_by(TeamRow.name, TeamRow.id))
            return [to_team(row) for row in rows]
        return await self.teams.list_for_user(session, caller.user_id)

    async def team_members(
        self, session: AsyncSession, caller: CallerPrincipal, team_id: TeamId
    ) -> list[TeamMembership]:
        actor = await self.current_user(session, caller)
        row = await self.teams.get(session, team_id)
        if row is None or (
            actor.role is not UserRole.SUPERUSER
            and not await self.teams.active_member(session, team_id, caller.user_id)
        ):
            raise AccessDenied("Team access denied")
        if actor.role is UserRole.SUPERUSER:
            self._audit(
                session,
                actor=caller.user_id,
                project=None,
                action="operator.team_members_read",
                target=team_id,
            )
        return await self.teams.list_members(session, team_id)

    async def add_team_member(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        team_id: TeamId,
        user_id: UserId,
        expected_version: int,
    ) -> TeamMembership:
        actor = await self.current_user(session, caller, lock=True)
        # The Team row is locked for member/owner transitions.
        row = await self.teams.get(session, team_id, lock=True)
        if row is None:
            raise AccessDenied("Team access denied")
        if row.version != expected_version:
            raise Conflict("Team version mismatch")
        if actor.role is not UserRole.SUPERUSER:
            require_team_owner(to_team(row), caller.user_id)
        target = await self.users.get_user(session, user_id, lock=True)
        if target is None or not target.enabled:
            raise ResourceMissing("User is not active")
        member = await self.teams.member_row(session, team_id, user_id)
        if member is None:
            member = TeamMembershipRow(
                id=uuid4(), team_id=team_id, user_id=user_id, active=True, version=1
            )
            session.add(member)
        elif not member.active:
            member.active = True
            member.version += 1
        else:
            return TeamMembership(team_id, user_id, True)
        row.version += 1
        self._audit(
            session,
            actor=caller.user_id,
            project=None,
            action="team.member_added",
            target=user_id,
            event={"team_id": str(team_id)},
        )
        return TeamMembership(team_id, user_id, True)

    async def remove_team_member(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        team_id: TeamId,
        user_id: UserId,
        expected_version: int,
    ) -> TeamMembership:
        actor = await self.current_user(session, caller, lock=True)
        row = await self.teams.get(session, team_id, lock=True)
        if row is None:
            raise AccessDenied("Team access denied")
        if row.version != expected_version:
            raise Conflict("Team version mismatch")
        if actor.role is not UserRole.SUPERUSER:
            require_team_owner(to_team(row), caller.user_id)
        if row.owner_user_id == user_id:
            raise Conflict("Team owner cannot be removed from membership")
        member = await self.teams.member_row(session, team_id, user_id)
        if member is None:
            raise ResourceMissing("member not found")
        if member.active:
            member.active = False
            member.version += 1
            row.version += 1
            self._audit(
                session,
                actor=caller.user_id,
                project=None,
                action="team.member_removed",
                target=user_id,
                event={"team_id": str(team_id)},
            )
        return TeamMembership(team_id, user_id, False)

    async def transfer_team_owner(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        team_id: TeamId,
        new_owner: UserId,
        expected_version: int,
    ) -> Team:
        actor = await self.current_user(session, caller, lock=True)
        row = await self.teams.get(session, team_id, lock=True)
        if row is None:
            raise AccessDenied("Team access denied")
        if row.version != expected_version:
            raise Conflict("Team version mismatch")
        if actor.role is not UserRole.SUPERUSER:
            require_team_owner(to_team(row), caller.user_id)
        if not await self.teams.active_member(session, team_id, new_owner):
            raise Conflict("new owner must be an active Team member")
        target = await self.users.get_user(session, new_owner, lock=True)
        if target is None or not target.enabled:
            raise Conflict("new owner must be an enabled User")
        if row.owner_user_id != new_owner:
            row.owner_user_id = new_owner
            row.version += 1
            self._audit(
                session,
                actor=caller.user_id,
                project=None,
                action="team.owner_transferred",
                target=team_id,
                event={"new_owner_id": str(new_owner)},
            )
        return to_team(row)

    async def create_project(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        *,
        name: str,
        team_id: TeamId | None = None,
    ) -> Project:
        await self.current_user(session, caller, lock=True)
        if team_id is not None:
            team = await self.teams.get(session, team_id, lock=True)
            if team is None or not await self.teams.active_member(session, team_id, caller.user_id):
                raise AccessDenied("Team access denied")
        row = ProjectRow(
            id=uuid4(),
            name=_name(name),
            owner_user_id=caller.user_id if team_id is None else None,
            owner_team_id=team_id,
            version=1,
        )
        session.add(row)
        await session.flush()
        self._audit(
            session,
            actor=caller.user_id,
            project=PlatformProjectId(row.id),
            action="project.created",
            target=row.id,
        )
        return to_project(row)

    async def visible_projects(
        self, session: AsyncSession, caller: CallerPrincipal
    ) -> list[Project]:
        user = await self.current_user(session, caller)
        if user.role is UserRole.SUPERUSER:
            self._audit(
                session,
                actor=caller.user_id,
                project=None,
                action="operator.projects_read",
                target="projects",
            )
            rows = await session.scalars(
                select(ProjectRow).order_by(ProjectRow.name, ProjectRow.id)
            )
            return [to_project(row) for row in rows]
        teams = await self.teams.list_for_user(session, caller.user_id)
        return await self.projects.by_owners(session, caller.user_id, [team.id for team in teams])

    async def transfer_project_to_team(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        team_id: TeamId,
        expected_version: int,
    ) -> Project:
        await self.current_user(session, caller, lock=True)
        row = await self.projects.get(session, project_id, lock=True)
        if row is None:
            raise AccessDenied("Project access denied")
        if row.version != expected_version:
            raise Conflict("Project version mismatch")
        require_personal_owner(to_project(row), caller.user_id)
        team = await self.teams.get(session, team_id, lock=True)
        if team is None or not await self.teams.active_member(session, team_id, caller.user_id):
            raise AccessDenied("Team access denied")
        row.owner_user_id = None
        row.owner_team_id = team_id
        row.version += 1
        self._audit(
            session,
            actor=caller.user_id,
            project=project_id,
            action="project.transferred_to_team",
            target=project_id,
            event={"team_id": str(team_id), "old_owner_user_id": str(caller.user_id)},
        )
        return to_project(row)

    async def withdraw_project_to_personal(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        expected_version: int,
    ) -> Project:
        actor = await self.current_user(session, caller, lock=True)
        row = await self.projects.get(session, project_id, lock=True)
        if row is None or row.owner_team_id is None:
            raise AccessDenied("Team Project access denied")
        if row.version != expected_version:
            raise Conflict("Project version mismatch")
        team = await self.teams.get(session, TeamId(row.owner_team_id), lock=True)
        if team is None or (
            team.owner_user_id != caller.user_id and actor.role is not UserRole.SUPERUSER
        ):
            raise AccessDenied("Team owner required to withdraw Project")
        previous_team_id = row.owner_team_id
        row.owner_team_id = None
        row.owner_user_id = caller.user_id
        row.version += 1
        self._audit(
            session,
            actor=caller.user_id,
            project=project_id,
            action="project.withdrawn_to_personal",
            target=project_id,
            event={
                "old_team_id": str(previous_team_id),
                "new_owner_user_id": str(caller.user_id),
            },
        )
        return to_project(row)

    async def create_agent(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        *,
        name: str,
        parent_id: AgentIdentityId | None = None,
    ) -> AgentIdentity:
        await self.project_allowed(session, caller, project_id, for_write=True)
        if parent_id is not None:
            parent = await self.agents.get(session, parent_id, lock=True)
            if parent is None or parent.project_id != project_id or not parent.enabled:
                raise AccessDenied("Agent parent is not in current Project")
        row = AgentIdentityRow(
            id=uuid4(),
            project_id=project_id,
            parent_agent_id=parent_id,
            name=_name(name),
            enabled=True,
        )
        session.add(row)
        await session.flush()
        self._audit(
            session,
            actor=caller.user_id,
            project=project_id,
            action="agent.created",
            target=row.id,
        )
        return to_agent(row)

    async def rename_agent(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        agent_id: AgentIdentityId,
        *,
        expected_version: int,
        name: str,
    ) -> AgentIdentity:
        await self.project_allowed(session, caller, project_id, for_write=True)
        row = await self.agents.get(session, agent_id, lock=True)
        if row is None or row.project_id != project_id:
            raise AccessDenied("Agent unavailable in selected Project")
        if row.version != expected_version:
            raise Conflict("Agent revision mismatch")
        row.name = _name(name)
        row.version += 1
        self._audit(
            session,
            actor=caller.user_id,
            project=project_id,
            action="agent.renamed",
            target=agent_id,
            event={"agent_version": row.version},
        )
        return to_agent(row)

    async def set_agent_enabled(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        agent_id: AgentIdentityId,
        *,
        expected_version: int,
        enabled: bool,
    ) -> AgentIdentity:
        """Explicit AgentIdentity lifecycle; no cascade into AgentSessions.

        Parent is locked before enabling a child. Creating a child also locks
        its parent. Disabling a parent with active children is rejected.
        """
        await self.project_allowed(session, caller, project_id, for_write=True)
        probe = await self.agents.get(session, agent_id)
        if probe is None or probe.project_id != project_id:
            raise AccessDenied("Agent unavailable in selected Project")
        if enabled and probe.parent_agent_id is not None:
            parent = await self.agents.get(
                session, AgentIdentityId(probe.parent_agent_id), lock=True
            )
            if parent is None or parent.project_id != project_id or not parent.enabled:
                raise Conflict("parent AgentIdentity must be enabled")
        row = await self.agents.get(session, agent_id, lock=True)
        if row is None or row.project_id != project_id:
            raise AccessDenied("Agent unavailable in selected Project")
        if row.version != expected_version:
            raise Conflict("Agent revision mismatch")
        if row.enabled == enabled:
            return to_agent(row)
        if not enabled:
            child = await session.scalar(
                select(AgentIdentityRow.id)
                .where(
                    AgentIdentityRow.project_id == project_id,
                    AgentIdentityRow.parent_agent_id == agent_id,
                    AgentIdentityRow.enabled.is_(True),
                )
                .limit(1)
            )
            if child is not None:
                raise Conflict("disable active child agents before their parent")
        row.enabled = enabled
        row.version += 1
        self._audit(
            session,
            actor=caller.user_id,
            project=project_id,
            action="agent.enabled" if enabled else "agent.disabled",
            target=agent_id,
            event={"agent_version": row.version},
        )
        return to_agent(row)

    async def agents_for_project(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
    ) -> list[AgentIdentity]:
        await self.project_allowed(session, caller, project_id)
        return await self.agents.list_for_project(session, project_id)

    async def project_permissions(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
    ) -> list[ProjectPermission]:
        await self.project_allowed(session, caller, project_id)
        return [
            ProjectPermission.USE_RESOURCES,
            ProjectPermission.APPROVE_AGENT_SESSION,
        ]

    async def admin_reassign_project(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        *,
        expected_version: int,
        new_owner_user_id: UserId | None = None,
        new_owner_team_id: TeamId | None = None,
    ) -> Project:
        """Explicit recovery transfer by verified superuser; no resource deletion."""
        actor = await self.current_user(session, caller, lock=True)
        if actor.role is not UserRole.SUPERUSER:
            raise AccessDenied("active superuser required")
        if (new_owner_user_id is None) == (new_owner_team_id is None):
            raise InvalidInput("Project must have exactly one new owner")
        row = await self.projects.get(session, project_id, lock=True)
        if row is None:
            raise AccessDenied("Project access denied")
        if row.version != expected_version:
            raise Conflict("Project version mismatch")
        if new_owner_user_id is not None:
            target = await self.users.get_user(session, new_owner_user_id, lock=True)
            if target is None or not target.enabled:
                raise Conflict("new personal Project owner must be active")
        if new_owner_team_id is not None:
            team = await self.teams.get(session, new_owner_team_id, lock=True)
            if team is None:
                raise Conflict("new owning Team does not exist")
        previous_owner_user = row.owner_user_id
        previous_owner_team = row.owner_team_id
        row.owner_user_id = new_owner_user_id
        row.owner_team_id = new_owner_team_id
        row.version += 1
        self._audit(
            session,
            actor=caller.user_id,
            project=project_id,
            action="project.admin_reassigned",
            target=project_id,
            event={
                "new_owner_user_id": str(new_owner_user_id) if new_owner_user_id else None,
                "new_owner_team_id": str(new_owner_team_id) if new_owner_team_id else None,
                "old_owner_user_id": str(previous_owner_user) if previous_owner_user else None,
                "old_team_id": str(previous_owner_team) if previous_owner_team else None,
            },
        )
        return to_project(row)

    async def delete_user(
        self, session: AsyncSession, caller: CallerPrincipal, user_id: UserId
    ) -> User:
        """Soft-delete identity only; never cascade resources or sessions."""
        await self.users.lock_bootstrap(session)
        actor = await self.current_user(session, caller, lock=True)
        if actor.role is not UserRole.SUPERUSER:
            raise AccessDenied("active superuser required")
        user = await self.users.get_user(session, user_id, lock=True)
        if user is None or user.deleted_at is not None:
            raise ResourceMissing("User not found")
        if await self.teams.owner_team_exists(session, user_id):
            raise Conflict("transfer owned Teams before deleting User")
        if await self.projects.user_owns_any(session, user_id):
            raise Conflict("transfer owned personal Projects before deleting User")
        if user.role == "superuser" and user.enabled:
            active = await self.users.list_active_superusers(session)
            if len(active) <= 1:
                raise Conflict("cannot delete the last active superuser")
        from identity._service import utcnow

        now = utcnow()
        user.deleted_at = now
        user.enabled = False
        user.credential_version += 1
        user.username = f"deleted-{user.id}"
        user.password_digest = "deleted-no-password"
        user.updated_at = now
        await self.users.revoke_outstanding_invitations(session, user_id, now)
        await self.teams.deactivate_user_memberships(session, user_id)
        self._audit(
            session,
            actor=caller.user_id,
            project=None,
            action="identity.deleted",
            target=user_id,
        )
        return to_user(user)
