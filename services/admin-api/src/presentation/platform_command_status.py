# ruff: noqa: B008  # FastAPI dependencies
"""Private source-only idempotent command reconciliation for Frontend clients.

This never decrypts a previously stored response and never promises that
absence of an idempotency record proves the external side effect failed.
Reads require current authenticated User AND Project rights every time.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._platform_permissions import team_permit
from authorization._platform_persistence import IdempotencyRow
from authorization._project_access import CallerPrincipal
from common.platform_errors import AccessDenied, InvalidInput
from common.platform_ids import PlatformProjectId, TeamId
from projects._resource_persistence import IntegrationRow, VariableRow
from projects._resource_service import ResourceService, owner_of

Caller = Callable[..., Awaitable[CallerPrincipal]]


class CommandStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    operation: str
    state: Literal["not_found", "pending", "completed"]
    outcome_http_status: int | None = None
    expires_at: datetime | None = None
    # A missing result is NOT permission to blindly generate a second key.
    reconciliation_required: bool = True


class ScopedCommandStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_kind: Literal["team", "project_resource", "resource"]
    scope_id: UUID
    operation: str
    state: Literal["not_found", "pending", "completed"]
    outcome_http_status: int | None = None
    expires_at: datetime | None = None
    reconciliation_required: bool = True


async def _command_record(
    tx: AsyncSession,
    *,
    actor_id: UUID,
    scope: str,
    operation: str,
    key: str,
) -> IdempotencyRow | None:
    return cast(
        IdempotencyRow | None,
        await tx.scalar(
            select(IdempotencyRow).where(
                IdempotencyRow.actor_scope == str(actor_id),
                IdempotencyRow.project_scope == scope,
                IdempotencyRow.operation == operation,
                IdempotencyRow.key == key,
            )
        ),
    )


def _scope_response(
    kind: Literal["team", "project_resource", "resource"],
    ident: UUID,
    operation: str,
    row: IdempotencyRow | None,
) -> ScopedCommandStatus:
    state: Literal["not_found", "pending", "completed"] = "not_found"
    if row is not None:
        state = (
            "completed"
            if row.status == "completed" and row.response_ciphertext is not None
            else "pending"
        )
    return ScopedCommandStatus(
        scope_kind=kind,
        scope_id=ident,
        operation=operation,
        state=state,
        outcome_http_status=(
            row.response_status if row is not None and state == "completed" else None
        ),
        expires_at=row.expires_at if row is not None else None,
        reconciliation_required=state != "completed",
    )


def _validate_query(operation: str, key: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", operation):
        raise InvalidInput("unsupported command operation selector")
    if not key.isascii() or not key.isprintable():
        raise InvalidInput("Idempotency-Key must be printable ASCII")


def build_unmounted_command_status_router(
    app: PlatformApplication,
    verified_caller: Caller,
    resources: ResourceService | None = None,
) -> APIRouter:
    router = APIRouter(tags=["platform-command-reconciliation-draft"])

    @router.get(
        "/projects/{project_id}/commands/{operation}/status",
        response_model=CommandStatus,
    )
    async def inspect_scoped_command(
        project_id: UUID,
        operation: str = Path(min_length=1, max_length=128),
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> CommandStatus:
        _validate_query(operation, key)
        project = PlatformProjectId(project_id)
        async with app.db.transaction() as tx:
            await app.project_allowed(tx, caller, project)
            row = await _command_record(
                tx,
                actor_id=caller.user_id,
                scope=str(project),
                operation=operation,
                key=key,
            )
            if row is None:
                return CommandStatus(
                    project_id=project_id,
                    operation=operation,
                    state="not_found",
                    reconciliation_required=True,
                )
            if row.status == "completed" and row.response_ciphertext is not None:
                return CommandStatus(
                    project_id=project_id,
                    operation=operation,
                    state="completed",
                    outcome_http_status=row.response_status,
                    expires_at=row.expires_at,
                    reconciliation_required=False,
                )
            return CommandStatus(
                project_id=project_id,
                operation=operation,
                state="pending",
                expires_at=row.expires_at,
                reconciliation_required=True,
            )

    @router.get(
        "/teams/{team_id}/commands/{operation}/status",
        response_model=ScopedCommandStatus,
    )
    async def team_command_status(
        team_id: UUID,
        operation: str = Path(min_length=1, max_length=128),
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> ScopedCommandStatus:
        _validate_query(operation, key)
        async with app.db.transaction() as tx:
            # Lock the active User then the authoritative Team before reading
            # a previously committed command. A Team member cannot inspect
            # an owner's membership/ownership mutation just by guessing a key.
            await app.current_user(tx, caller, lock=True)
            team = await app.teams.get(tx, TeamId(team_id), lock=True)
            if team is None:
                raise AccessDenied("Team unavailable")
            permit = await team_permit(tx, app, caller, TeamId(team_id))
            stored_operation = operation
            if operation in {"integration.create", "variable.create"}:
                if not permit.can_manage_resources:
                    raise AccessDenied("Team resource permission required")
                scope = f"team:{team_id}"
            elif operation in {
                "team.member.add", "team.member.remove", "team.transfer_owner"
            }:
                if not permit.can_manage_members:
                    raise AccessDenied("current Team owner permission required")
                # The original accepted write API persists these commands
                # in the GLOBAL actor scope with Team UUID in operation.
                # Never change the durable dedupe identity to fit a read API,
                # and never search alternate/fallback scopes after UNKNOWN.
                scope = "global"
                stored_operation = f"{operation}:{team_id}"
            else:
                raise InvalidInput("unsupported Team command status operation")
            row = await _command_record(
                tx,
                actor_id=caller.user_id,
                scope=scope,
                operation=stored_operation,
                key=key,
            )
            return _scope_response("team", team_id, operation, row)

    @router.get(
        "/projects/{project_id}/resource-commands/{operation}/status",
        response_model=ScopedCommandStatus,
    )
    async def project_resource_create_status(
        project_id: UUID,
        operation: str = Path(min_length=1, max_length=128),
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> ScopedCommandStatus:
        _validate_query(operation, key)
        if operation not in {"integration.create", "variable.create"}:
            raise InvalidInput("unsupported Project resource-create status operation")
        async with app.db.transaction() as tx:
            await app.project_allowed(tx, caller, PlatformProjectId(project_id))
            row = await _command_record(
                tx,
                actor_id=caller.user_id,
                scope=f"project:{project_id}",
                operation=operation,
                key=key,
            )
            return _scope_response("project_resource", project_id, operation, row)

    if resources is not None:

        @router.get(
            "/resources/{resource_id}/commands/{operation}/status",
            response_model=ScopedCommandStatus,
        )
        async def resource_command_status(
            resource_id: UUID,
            operation: str = Path(min_length=1, max_length=128),
            key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
            caller: CallerPrincipal = Depends(verified_caller),
        ) -> ScopedCommandStatus:
            _validate_query(operation, key)
            record_type: type[IntegrationRow] | type[VariableRow]
            if operation.startswith("integration."):
                record_type = IntegrationRow
            elif operation.startswith("variable."):
                record_type = VariableRow
            else:
                raise InvalidInput("unsupported resource status operation")
            if operation.split(".")[-1] not in {"update", "rotate", "revoke"}:
                raise InvalidInput("unsupported resource lifecycle operation")
            async with app.db.transaction() as tx:
                record = cast(
                    IntegrationRow | VariableRow | None,
                    await tx.scalar(select(record_type).where(record_type.id == resource_id)),
                )
                if record is None:
                    raise AccessDenied("resource unavailable to this User")
                owner = owner_of(record)
                await resources._check_owner(tx, caller, owner, lock=True)
                # A concurrent ownership transfer cannot change visibility
                # before this transaction's owner-row lock is acquired.
                refreshed = cast(
                    IntegrationRow | VariableRow | None,
                    await tx.scalar(
                        select(record_type)
                        .where(record_type.id == resource_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    ),
                )
                if refreshed is None or owner_of(refreshed) != owner:
                    raise AccessDenied("resource owner changed during lookup")
                row = await _command_record(
                    tx,
                    actor_id=caller.user_id,
                    scope=f"resource:{resource_id}",
                    operation=operation,
                    key=key,
                )
                return _scope_response("resource", resource_id, operation, row)

    return router
