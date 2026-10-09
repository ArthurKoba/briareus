"""Project persistence projections, independent from Team membership data."""

from __future__ import annotations

from typing import cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_ids import PlatformProjectId, TeamId, UserId
from projects._domain import Project

from ._persistence import ProjectRow


def to_project(row: ProjectRow) -> Project:
    return Project(
        PlatformProjectId(row.id),
        row.name,
        UserId(row.owner_user_id) if row.owner_user_id else None,
        TeamId(row.owner_team_id) if row.owner_team_id else None,
        row.version,
    )


class ProjectRepository:
    async def get(
        self, session: AsyncSession, project_id: PlatformProjectId, *, lock: bool = False
    ) -> ProjectRow | None:
        query = select(ProjectRow).where(ProjectRow.id == project_id)
        if lock:
            query = query.with_for_update()
        return cast(ProjectRow | None, await session.scalar(query))

    async def by_owners(
        self, session: AsyncSession, user_id: UserId, team_ids: list[TeamId]
    ) -> list[Project]:
        clauses = [ProjectRow.owner_user_id == user_id]
        if team_ids:
            clauses.append(ProjectRow.owner_team_id.in_(team_ids))
        result = await session.scalars(
            select(ProjectRow).where(or_(*clauses)).order_by(ProjectRow.name, ProjectRow.id)
        )
        return [to_project(row) for row in result]

    async def user_owns_any(self, session: AsyncSession, user_id: UserId) -> bool:
        return (
            await session.scalar(
                select(ProjectRow.id).where(ProjectRow.owner_user_id == user_id).limit(1)
            )
            is not None
        )
