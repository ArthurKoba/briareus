"""Repository for independent Team-or-Project resources, no global name lookup."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from projects._resource_domain import ResourceOwner

from ._resource_persistence import IntegrationRow, VariableRow


class ResourceRepository:
    async def integration(
        self,
        tx: AsyncSession,
        resource_id: UUID,
        *,
        lock: bool = False,
    ) -> IntegrationRow | None:
        query = select(IntegrationRow).where(
            IntegrationRow.id == resource_id,
            IntegrationRow.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        return cast(IntegrationRow | None, await tx.scalar(query))

    async def variable(
        self,
        tx: AsyncSession,
        resource_id: UUID,
        *,
        lock: bool = False,
    ) -> VariableRow | None:
        query = select(VariableRow).where(
            VariableRow.id == resource_id,
            VariableRow.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        return cast(VariableRow | None, await tx.scalar(query))

    @staticmethod
    def _owner_filter(
        row_type: type[IntegrationRow] | type[VariableRow],
        owner: ResourceOwner,
    ) -> ColumnElement[bool]:
        return (
            row_type.owner_team_id == owner.owner_id
            if owner.team_id is not None
            else row_type.owner_project_id == owner.owner_id
        )

    async def integrations_for(
        self,
        tx: AsyncSession,
        owner: ResourceOwner,
    ) -> list[IntegrationRow]:
        rows = await tx.scalars(
            select(IntegrationRow)
            .where(
                self._owner_filter(IntegrationRow, owner),
                IntegrationRow.deleted_at.is_(None),
            )
            .order_by(IntegrationRow.alias_key, IntegrationRow.id)
        )
        return list(rows)

    async def variables_for(
        self,
        tx: AsyncSession,
        owner: ResourceOwner,
    ) -> list[VariableRow]:
        rows = await tx.scalars(
            select(VariableRow)
            .where(
                self._owner_filter(VariableRow, owner),
                VariableRow.deleted_at.is_(None),
            )
            .order_by(VariableRow.name_key, VariableRow.id)
        )
        return list(rows)
