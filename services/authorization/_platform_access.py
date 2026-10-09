"""SQL-backed adapters for accepted internal C1-A Authorization ports.

Adapters share one *sequential* Unit of Work, never concurrent AsyncSession use.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_ids import PlatformProjectId, TeamId, UserId
from identity._repository import IdentityRepository
from projects._repository import ProjectRepository
from teams._repository import TeamRepository

from ._project_access import PlatformRole, ProjectOwnership, UserAccessState


class SqlUserAccess:
    def __init__(self, session: AsyncSession, users: IdentityRepository) -> None:
        self.session = session
        self.users = users

    async def get_current_user(self, user_id: UserId) -> UserAccessState | None:
        row = await self.users.get_user(self.session, user_id)
        if row is None:
            return None
        try:
            role = PlatformRole(row.role)
        except ValueError:
            # Unknown database role is never a superuser.
            return None
        return UserAccessState(enabled=row.enabled, role=role)


class SqlProjectOwnership:
    def __init__(self, session: AsyncSession, projects: ProjectRepository) -> None:
        self.session = session
        self.projects = projects

    async def get_ownership(self, project_id: PlatformProjectId) -> ProjectOwnership | None:
        row = await self.projects.get(self.session, project_id)
        if row is None:
            return None
        return ProjectOwnership(
            project_id=PlatformProjectId(row.id),
            owner_user_id=UserId(row.owner_user_id) if row.owner_user_id else None,
            owner_team_id=TeamId(row.owner_team_id) if row.owner_team_id else None,
        )


class SqlMembership:
    def __init__(self, session: AsyncSession, teams: TeamRepository) -> None:
        self.session = session
        self.teams = teams

    async def is_active_member(self, team_id: TeamId, user_id: UserId) -> bool:
        return await self.teams.active_member(self.session, team_id, user_id)
