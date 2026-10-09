# ruff: noqa: B008  # FastAPI dependency/query descriptors
"""Bounded, Project/Team-authorized keyset pages for A6 Admin readers.

These are additive source-only routes. Historical list responses stay valid.
A UUID cursor selects the next stable UUID-ordered page; it does NOT grant
authority and is NEVER an alternative to current JWT, User or scope checks.
Concurrent mutations may change subsequent page membership (not a snapshot).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._platform_permissions import project_permit, team_permit
from authorization._project_access import CallerPrincipal
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from common.platform_errors import AccessDenied, InvalidInput
from common.platform_ids import PlatformProjectId, TeamId
from identity._domain import UserRole
from identity._persistence import InvitationRow, UserRow
from projects._persistence import ProjectRow
from teams._persistence import TeamMembershipRow, TeamRow

from .platform_overview_api import (
    ApprovalDisplay,
    InvitationDisplay,
    MemberDisplay,
    SessionDisplay,
    UserDisplay,
    _grants,
    user_allowed_actions,
)

Caller = Callable[..., Awaitable[CallerPrincipal]]


class Page[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[T]
    next_after_id: UUID | None
    has_more: bool
    page_size: int = Field(ge=1, le=250)


def _validate_after(after: UUID | None) -> UUID | None:
    if after is not None and after.version != 4:
        raise InvalidInput("page cursor must be a UUIDv4")
    return after


def _page[T](
    items: list[T],
    *,
    limit: int,
    id_of: Callable[[T], UUID],
) -> Page[T]:
    visible = items[:limit]
    more = len(items) > limit
    return Page[T](
        items=visible,
        next_after_id=id_of(visible[-1]) if visible and more else None,
        has_more=more,
        page_size=limit,
    )


async def _lock_team(
    tx: AsyncSession,
    app: PlatformApplication,
    caller: CallerPrincipal,
    team_id: TeamId,
) -> None:
    await app.current_user(tx, caller, lock=True)
    if await app.teams.get(tx, team_id, lock=True) is None:
        raise AccessDenied("Team not available")
    await team_permit(tx, app, caller, team_id)


async def _lock_project(
    tx: AsyncSession,
    app: PlatformApplication,
    caller: CallerPrincipal,
    project_id: PlatformProjectId,
) -> None:
    await app.current_user(tx, caller, lock=True)
    project = await app.projects.get(tx, project_id, lock=True)
    if project is None:
        raise AccessDenied("Project not available")
    if (
        project.owner_team_id is not None
        and await app.teams.get(tx, TeamId(project.owner_team_id), lock=True) is None
    ):
        raise AccessDenied("owning Team not available")
    await project_permit(tx, app, caller, project_id)


def build_unmounted_pages_router(
    app: PlatformApplication,
    verified_caller: Caller,
) -> APIRouter:
    router = APIRouter(tags=["platform-pages-draft"])

    @router.get("/users/page", response_model=Page[UserDisplay])
    async def users_page(
        limit: int = Query(default=100, ge=1, le=250),
        after: UUID | None = Query(default=None),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> Page[UserDisplay]:
        _validate_after(after)
        async with app.db.transaction() as tx:
            actor = await app.current_user(tx, caller, lock=True)
            if actor.role is not UserRole.SUPERUSER:
                raise AccessDenied("superuser permission required")
            query = (
                select(UserRow)
                .where(UserRow.deleted_at.is_(None))
                .order_by(UserRow.id)
                .limit(limit + 1)
            )
            if after is not None:
                query = query.where(UserRow.id > after)
            rows = list(await tx.scalars(query))
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
            active_admin_count = int(
                await tx.scalar(
                    select(func.count(UserRow.id)).where(
                        UserRow.role == "superuser",
                        UserRow.enabled.is_(True),
                        UserRow.deleted_at.is_(None),
                    )
                )
                or 0
            )
            app._audit(
                tx,
                actor=caller.user_id,
                project=None,
                action="operator.users_read",
                target="users",
            )
            items = [
                UserDisplay(
                    user_id=row.id,
                    username=row.username,
                    enabled=row.enabled,
                    role=row.role,
                    credential_version=row.credential_version,
                    allowed_actions=user_allowed_actions(
                        row,
                        active_admin_count=active_admin_count,
                        owned_teams=owned_teams,
                        owned_projects=owned_projects,
                    ),
                )
                for row in rows
            ]
            return _page(items, limit=limit, id_of=lambda row: row.user_id)

    @router.get("/teams/{team_id}/member-details/page", response_model=Page[MemberDisplay])
    async def team_members_page(
        team_id: UUID,
        limit: int = Query(default=100, ge=1, le=250),
        after: UUID | None = Query(default=None),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> Page[MemberDisplay]:
        _validate_after(after)
        async with app.db.transaction() as tx:
            await _lock_team(tx, app, caller, TeamId(team_id))
            query = (
                select(TeamMembershipRow, UserRow)
                .join(UserRow, UserRow.id == TeamMembershipRow.user_id)
                .where(
                    TeamMembershipRow.team_id == team_id,
                    UserRow.deleted_at.is_(None),
                )
                .order_by(TeamMembershipRow.user_id)
                .limit(limit + 1)
            )
            if after is not None:
                query = query.where(TeamMembershipRow.user_id > after)
            rows = (await tx.execute(query)).all()
            items = [
                MemberDisplay(
                    team_id=team_id,
                    user_id=user.id,
                    username=user.username,
                    enabled=user.enabled,
                    active=membership.active,
                )
                for membership, user in rows
            ]
            return _page(items, limit=limit, id_of=lambda row: row.user_id)

    @router.get("/invitations/page", response_model=Page[InvitationDisplay])
    async def invitations_page(
        limit: int = Query(default=100, ge=1, le=250),
        after: UUID | None = Query(default=None),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> Page[InvitationDisplay]:
        _validate_after(after)
        async with app.db.transaction() as tx:
            actor = await app.current_user(tx, caller, lock=True)
            query = select(InvitationRow).order_by(InvitationRow.id).limit(limit + 1)
            if after is not None:
                query = query.where(InvitationRow.id > after)
            if actor.role is not UserRole.SUPERUSER:
                query = query.where(InvitationRow.created_by_user_id == caller.user_id)
            rows = list(await tx.scalars(query))
            items = [
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
                for row in rows
            ]
            return _page(items, limit=limit, id_of=lambda row: row.invitation_id)

    @router.get(
        "/projects/{project_id}/sessions/page",
        response_model=Page[SessionDisplay],
    )
    async def project_sessions_page(
        project_id: UUID,
        limit: int = Query(default=100, ge=1, le=250),
        after: UUID | None = Query(default=None),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> Page[SessionDisplay]:
        _validate_after(after)
        async with app.db.transaction() as tx:
            await _lock_project(tx, app, caller, PlatformProjectId(project_id))
            query = (
                select(ProjectAgentSessionRow)
                .where(ProjectAgentSessionRow.project_id == project_id)
                .order_by(ProjectAgentSessionRow.session_uuid)
                .limit(limit + 1)
            )
            if after is not None:
                query = query.where(ProjectAgentSessionRow.session_uuid > after)
            rows = list(await tx.scalars(query))
            items = [
                SessionDisplay(
                    session_uuid=row.session_uuid,
                    project_id=row.project_id,
                    label=row.label,
                    status=row.status,
                    grants=_grants(row.grants),
                    is_elevated=row.is_elevated,
                    elevation_policy=row.elevation_policy,
                    hard_expires_at=row.hard_expires_at,
                    created_at=row.created_at,
                    version=row.version,
                )
                for row in rows
            ]
            return _page(items, limit=limit, id_of=lambda row: row.session_uuid)

    @router.get(
        "/projects/{project_id}/approvals/page",
        response_model=Page[ApprovalDisplay],
    )
    async def project_approvals_page(
        project_id: UUID,
        limit: int = Query(default=100, ge=1, le=250),
        after: UUID | None = Query(default=None),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> Page[ApprovalDisplay]:
        _validate_after(after)
        async with app.db.transaction() as tx:
            await _lock_project(tx, app, caller, PlatformProjectId(project_id))
            query = (
                select(SessionApprovalRow)
                .where(SessionApprovalRow.project_id == project_id)
                .order_by(SessionApprovalRow.id)
                .limit(limit + 1)
            )
            if after is not None:
                query = query.where(SessionApprovalRow.id > after)
            rows = list(await tx.scalars(query))
            items = [
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
                for row in rows
            ]
            return _page(items, limit=limit, id_of=lambda row: row.request_id)

    return router
