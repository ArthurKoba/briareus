"""Rauthy-only private write routes, with one current owner per Access DB.

Neither HTTP fields nor a Panel cookie can create the operator actor.
The attestor must verify independently signed Rauthy actor, Platform role,
private peer and exact operation/Project scope. Without it every path is 503.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from authorization._rauthy_access_commands import (
    AccessRauthyCommandService,
    OpenSessionCommand,
    RequestElevationCommand,
    ResolveElevationCommand,
    RevokeSessionCommand,
)
from common.platform_errors import AccessDenied, Conflict, IdempotencyConflict, InvalidInput


def rauthy_access_command_router(
    *,
    resolve_service: Callable[[], AccessRauthyCommandService | None],
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["access-private"])

    async def verified_command(request: Request, operation: UUID) -> None:
        if (
            request.headers.getlist("cookie")
            or request.headers.getlist("origin")
            or request.headers.getlist("authorization") == []
            or len(request.headers.getlist("authorization")) != 1
            or request.headers.getlist("content-type") != ["application/json"]
        ):
            raise HTTPException(401, detail="private authenticated service bearer required")
        if not 1 <= len(await request.body()) <= 32_768:
            raise HTTPException(413, detail="private Access command body too large")
        opaque = str(operation)
        if (
            operation.version != 4
            or request.headers.getlist("operation-uuid") != [opaque]
            or request.headers.getlist("idempotency-key") != [opaque]
        ):
            raise HTTPException(422, detail="canonical signed operation required")

    async def execute(
        request: Request,
        command: OpenSessionCommand
        | RequestElevationCommand
        | ResolveElevationCommand
        | RevokeSessionCommand,
    ) -> JSONResponse:
        owner = resolve_service()
        if owner is None:
            raise HTTPException(503, detail="trusted Access command source unavailable")
        await verified_command(request, command.operation_uuid)
        try:
            if isinstance(command, OpenSessionCommand):
                outcome = await owner.open_normal(request, command)
            elif isinstance(command, RequestElevationCommand):
                outcome = await owner.request_elevation(request, command)
            elif isinstance(command, ResolveElevationCommand):
                outcome = await owner.resolve_elevation(request, command)
            else:
                outcome = await owner.revoke_session(request, command)
        except AccessDenied:
            raise HTTPException(403, detail="current Project access denied") from None
        except (Conflict, IdempotencyConflict):
            raise HTTPException(409, detail="Access owner revision or replay conflict") from None
        except InvalidInput:
            raise HTTPException(422, detail="invalid signed Access request") from None
        except Exception:
            raise HTTPException(503, detail="Access owner unavailable") from None
        return JSONResponse(
            outcome.body,
            status_code=outcome.status,
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/sessions/open", include_in_schema=False)
    async def open_normal(command: OpenSessionCommand, request: Request) -> JSONResponse:
        return await execute(request, command)

    @router.post("/approvals/request", include_in_schema=False)
    async def request_elevation(command: RequestElevationCommand, request: Request) -> JSONResponse:
        return await execute(request, command)

    @router.post("/approvals/resolve", include_in_schema=False)
    async def resolve_elevation(command: ResolveElevationCommand, request: Request) -> JSONResponse:
        return await execute(request, command)

    @router.post("/sessions/revoke", include_in_schema=False)
    async def revoke_session(command: RevokeSessionCommand, request: Request) -> JSONResponse:
        return await execute(request, command)

    return router
