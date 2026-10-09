"""AgentIdentity persistence scoped to a canonical platform Project UUID."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents._domain import AgentIdentity
from common.platform_ids import AgentIdentityId, PlatformProjectId

from ._persistence import AgentIdentityRow


def to_agent(row: AgentIdentityRow) -> AgentIdentity:
    return AgentIdentity(
        id=AgentIdentityId(row.id),
        project_id=PlatformProjectId(row.project_id),
        name=row.name,
        parent_agent_id=AgentIdentityId(row.parent_agent_id) if row.parent_agent_id else None,
        enabled=row.enabled,
        version=row.version,
    )


class AgentIdentityRepository:
    async def get(
        self, session: AsyncSession, agent_id: AgentIdentityId, *, lock: bool = False
    ) -> AgentIdentityRow | None:
        query = select(AgentIdentityRow).where(AgentIdentityRow.id == agent_id)
        if lock:
            query = query.with_for_update()
        return cast(
            AgentIdentityRow | None,
            await session.scalar(query),
        )

    async def list_for_project(
        self, session: AsyncSession, project_id: PlatformProjectId
    ) -> list[AgentIdentity]:
        rows = await session.scalars(
            select(AgentIdentityRow)
            .where(AgentIdentityRow.project_id == project_id)
            .order_by(AgentIdentityRow.name, AgentIdentityRow.id)
        )
        return [to_agent(row) for row in rows]
