"""Teams repository; all writes use caller-owned transaction and locks."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_ids import TeamId, UserId
from teams._domain import Team, TeamMembership

from ._persistence import TeamMembershipRow, TeamRow


def to_team(row: TeamRow) -> Team:
    return Team(TeamId(row.id), row.name, UserId(row.owner_user_id), row.version)


class TeamRepository:
    async def get(
        self, session: AsyncSession, team_id: TeamId, *, lock: bool = False
    ) -> TeamRow | None:
        query = select(TeamRow).where(TeamRow.id == team_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return cast(TeamRow | None, await session.scalar(query))

    async def active_member(self, session: AsyncSession, team_id: TeamId, user_id: UserId) -> bool:
        return (
            await session.scalar(
                select(TeamMembershipRow.id).where(
                    TeamMembershipRow.team_id == team_id,
                    TeamMembershipRow.user_id == user_id,
                    TeamMembershipRow.active.is_(True),
                )
            )
            is not None
        )

    async def member_row(
        self, session: AsyncSession, team_id: TeamId, user_id: UserId
    ) -> TeamMembershipRow | None:
        return cast(
            TeamMembershipRow | None,
            await session.scalar(
                select(TeamMembershipRow)
                .where(TeamMembershipRow.team_id == team_id, TeamMembershipRow.user_id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )

    async def list_for_user(self, session: AsyncSession, user_id: UserId) -> list[Team]:
        query = (
            select(TeamRow)
            .join(TeamMembershipRow, TeamMembershipRow.team_id == TeamRow.id)
            .where(TeamMembershipRow.user_id == user_id, TeamMembershipRow.active.is_(True))
            .order_by(TeamRow.name, TeamRow.id)
        )
        return [to_team(row) for row in (await session.scalars(query)).all()]

    async def list_members(self, session: AsyncSession, team_id: TeamId) -> list[TeamMembership]:
        rows = await session.scalars(
            select(TeamMembershipRow)
            .where(TeamMembershipRow.team_id == team_id)
            .order_by(TeamMembershipRow.user_id)
        )
        return [
            TeamMembership(TeamId(row.team_id), UserId(row.user_id), row.active) for row in rows
        ]

    async def owner_team_exists(self, session: AsyncSession, user_id: UserId) -> bool:
        return (
            await session.scalar(
                select(TeamRow.id).where(TeamRow.owner_user_id == user_id).limit(1)
            )
            is not None
        )

    async def deactivate_user_memberships(self, session: AsyncSession, user_id: UserId) -> None:
        await session.execute(
            update(TeamMembershipRow)
            .where(
                TeamMembershipRow.user_id == user_id,
                TeamMembershipRow.active.is_(True),
            )
            .values(active=False, version=TeamMembershipRow.version + 1)
        )
