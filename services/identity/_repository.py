"""Transactional Identity queries and writes. Caller owns AsyncSession lifespan."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_ids import UserId
from identity._domain import User, UserRole

from ._persistence import BootstrapRow, InvitationRow, UserRow


def to_user(row: UserRow) -> User:
    return User(
        id=UserId(row.id),
        username=row.username,
        role=UserRole(row.role),
        enabled=row.enabled,
        credential_version=row.credential_version,
    )


class IdentityRepository:
    async def lock_bootstrap(self, session: AsyncSession) -> BootstrapRow:
        await session.execute(
            insert(BootstrapRow)
            .values(id=1, first_superuser_claimed=False)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        result = await session.scalar(
            select(BootstrapRow).where(BootstrapRow.id == 1).with_for_update()
        )
        assert result is not None
        return result

    async def get_user(
        self, session: AsyncSession, user_id: UserId, *, lock: bool = False
    ) -> UserRow | None:
        query: Select[tuple[UserRow]] = select(UserRow).where(UserRow.id == user_id)
        if lock:
            query = query.with_for_update()
        return cast(UserRow | None, await session.scalar(query))

    async def username_taken(self, session: AsyncSession, username: str) -> bool:
        return (
            await session.scalar(select(UserRow.id).where(UserRow.username == username)) is not None
        )

    async def username_row(self, session: AsyncSession, username: str) -> UserRow | None:
        return cast(
            UserRow | None,
            await session.scalar(select(UserRow).where(UserRow.username == username)),
        )

    async def get_invitation(
        self, session: AsyncSession, invitation_id: UUID, *, lock: bool = False
    ) -> InvitationRow | None:
        query = select(InvitationRow).where(InvitationRow.id == invitation_id)
        if lock:
            query = query.with_for_update()
        return cast(InvitationRow | None, await session.scalar(query))

    async def peek_invitation(
        self, session: AsyncSession, token_digest: str
    ) -> InvitationRow | None:
        return cast(
            InvitationRow | None,
            await session.scalar(
                select(InvitationRow).where(InvitationRow.token_digest == token_digest)
            ),
        )

    async def lock_invitation(
        self, session: AsyncSession, token_digest: str
    ) -> InvitationRow | None:
        return cast(
            InvitationRow | None,
            await session.scalar(
                select(InvitationRow)
                .where(InvitationRow.token_digest == token_digest)
                .with_for_update()
            ),
        )

    async def pending_system(self, session: AsyncSession) -> InvitationRow | None:
        return cast(
            InvitationRow | None,
            await session.scalar(
                select(InvitationRow)
                .where(
                    InvitationRow.kind == "system",
                    InvitationRow.used_at.is_(None),
                    InvitationRow.revoked_at.is_(None),
                )
                .order_by(InvitationRow.created_at, InvitationRow.id)
                .limit(1)
                .with_for_update()
            ),
        )

    async def revoke_outstanding_invitations(
        self, session: AsyncSession, issuer: UserId, when: datetime
    ) -> None:
        await session.execute(
            update(InvitationRow)
            .where(
                InvitationRow.created_by_user_id == issuer,
                InvitationRow.used_at.is_(None),
                InvitationRow.revoked_at.is_(None),
            )
            .values(revoked_at=when)
        )

    async def list_active_superusers(self, session: AsyncSession) -> list[UserRow]:
        result = await session.scalars(
            select(UserRow)
            .where(UserRow.role == "superuser", UserRow.enabled.is_(True))
            .order_by(UserRow.id)
        )
        return list(result)

    async def list_users(self, session: AsyncSession) -> list[User]:
        result = await session.scalars(select(UserRow).order_by(UserRow.username))
        return [to_user(r) for r in result]

    async def invitations_by_user(
        self, session: AsyncSession, user_id: UUID
    ) -> list[InvitationRow]:
        result = await session.scalars(
            select(InvitationRow).where(InvitationRow.created_by_user_id == user_id)
        )
        return list(result)
